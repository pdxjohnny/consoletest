import os
import sys
import subprocess
from typing import IO, List, Union


def sub_env_vars(cmd):
    for env_var_name, env_var_value in os.environ.items():
        for i, arg in enumerate(cmd):
            for check in ["$" + env_var_name, "${" + env_var_name + "}"]:
                if check in arg:
                    cmd[i] = arg.replace(check, env_var_value)
    return cmd


@contextlib.contextmanager
def tmpenv(cmd: List[str]) -> List[str]:
    """
    Handle temporary environment variables prepended to command
    """
    oldvars = {}
    tmpvars = {}
    for var in cmd:
        if "=" not in var:
            break
        cmd.pop(0)
        key, value = var.split("=", maxsplit=1)
        tmpvars[key] = value
        if key in os.environ:
            oldvars[key] = os.environ[key]
        os.environ[key] = value
    try:
        yield cmd
    finally:
        for key in tmpvars.keys():
            del os.environ[key]
        for key, value in oldvars.items():
            os.environ[key] = value


async def run_commands(
    cmds,
    ctx,
    *,
    stdin: Union[IO] = None,
    stdout: Union[IO] = None,
    ignore_errors: bool = False,
    daemon: bool = False,
    alternate_runners: Tuple = None,
):
    proc = None
    procs = []
    cmds = list(map(sub_env_vars, cmds))
    for i, cmd in enumerate(cmds):
        # Keyword arguments for Popen
        kwargs = {}
        # Set stdout to system stdout so it doesn't go to the pty
        kwargs["stdout"] = stdout if stdout is not None else sys.stdout
        # Check if there is a previous command
        kwargs["stdin"] = stdin if stdin is not None else subprocess.DEVNULL
        if i != 0:
            # NOTE asyncio.create_subprocess_exec doesn't work for piping output
            # from one process to the next. It will complain about stdin not
            # having a fileno()
            kwargs["stdin"] = proc.stdout
        # Check if there is a next command
        if i + 1 < len(cmds):
            kwargs["stdout"] = subprocess.PIPE
        # Check if we redirect stderr to stdout
        if "2>&1" in cmd:
            kwargs["stderr"] = subprocess.STDOUT
            cmd.remove("2>&1")
        # If not in venv ensure correct Python
        if (
            "VIRTUAL_ENV" not in os.environ
            and "CONDA_PREFIX" not in os.environ
            and cmd[0].startswith("python")
        ):
            cmd[0] = sys.executable
        # Handle temporary environment variables prepended to command
        with tmpenv(cmd) as cmd:
            if alternate_runners:
                # Check if there is an alternate runner
                found_alternate_runner = False
                for check, runner in alternate_runners:
                    found_alternate_runner = await check(cmd, ctx, kwargs)
                    if found_alternate_runner:
                        break
                if found_alternate_runner:
                    # Run the command using the alternate runner
                    proc = await runner(cmd, ctx, kwargs)
            else:
                # Run the command
                print()
                print("Running", cmd)
                print()
                proc = subprocess.Popen(
                    cmd, start_new_session=True, cwd=ctx["cwd"], **kwargs
                )
            proc.cmd = cmd
            procs.append(proc)
        # Parent (this Python process) close stdout of previous command so that
        # the command we just created has exclusive access to the output.
        if i != 0:
            kwargs["stdin"].close()
    # Wait for all processes to complete
    errors = []
    for i, proc in enumerate(procs):
        # Do not wait for last process to complete if running in daemon mode
        if daemon and (i + 1) == len(procs):
            break
        proc.wait()
        if proc.returncode != 0:
            errors.append(f"Failed to run: {cmd!r}")
    if errors and not ignore_errors:
        raise RuntimeError("\n".join(errors))
    if daemon:
        return procs[-1]
