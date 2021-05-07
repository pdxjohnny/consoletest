"""
Running of shell commands
"""
import os
import abc
import sys
import json
import time
import copy
import shlex
import signal
import atexit
import asyncio
import pathlib
import inspect
import tempfile
import functools
import contextlib
import subprocess
import http.server
from typing import IO, Any, Dict, List, Union, Optional


class ConsoletestCommand(abc.ABC):
    def __init__(self):
        self.poll_until = False
        self.compare_output = None
        self.compare_output_imports = None
        self.ignore_errors = False
        self.daemon = None

    def __repr__(self):
        return (
            self.__class__.__qualname__
            + "("
            + str(
                {
                    k: v
                    for k, v in self.__dict__.items()
                    if not k.startswith("_")
                }
            )
            + ")"
        )

    def __str__(self):
        return repr(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback):
        pass

    @classmethod
    def check(cls, cmd):
        raise NotImplementedError


class CDCommand(ConsoletestCommand):
    def __init__(self, directory: str):
        super().__init__()
        self.directory = directory

    def __eq__(self, other: "CDCommand"):
        return bool(
            hasattr(other, "directory") and self.directory == other.directory
        )

    async def run(self, ctx):
        ctx["cwd"] = os.path.abspath(os.path.join(ctx["cwd"], self.directory))

    @classmethod
    def check(cls, cmd):
        if cmd[:1] == ["cd"]:
            return cls(cmd[1])


class ActivateVirtualEnvCommand(ConsoletestCommand):
    def __init__(self, directory: str):
        super().__init__()
        self.directory = directory
        self.old_virtual_env = None
        self.old_virtual_env_dir = None
        self.old_path = None
        self.old_pythonpath = None
        self.old_sys_path = []
        # Functions to run after activation
        self.post_activate = set()

    def register_post_activate(self, func):
        self.post_activate.add(func)

    def unregister_post_activate(self, func):
        self.post_activate.remove(func)

    def __eq__(self, other: "ActivateVirtualEnvCommand"):
        return bool(
            hasattr(other, "directory") and self.directory == other.directory
        )

    @classmethod
    def check(cls, cmd):
        # Handle virtualenv activation
        if ".\\.venv\\Scripts\\activate" in cmd or (
            len(cmd) == 2
            and cmd[0] in ("source", ".")
            and ".venv/bin/activate" == cmd[1]
        ):
            return cls(".venv")

    async def run(self, ctx):
        self.old_virtual_env = os.environ.get("VIRTUAL_ENV", None)
        self.old_virtual_env_dir = os.environ.get("VIRTUAL_ENV_DIR", None)
        self.old_path = os.environ.get("PATH", None)
        self.old_pythonpath = os.environ.get("PYTHONPATH", None)
        env_path = os.path.abspath(os.path.join(ctx["cwd"], self.directory))
        os.environ["PATH"] = ":".join(
            [os.path.join(env_path, "bin")]
            + os.environ.get("PATH", "").split(":")
        )
        os.environ["PYTHONPATH"] = ":".join(
            os.environ.get("PYTHONPATH", "").split(":")
            + [
                os.path.join(
                    env_path,
                    "lib",
                    f"python{sys.version_info.major}.{sys.version_info.minor}",
                    "site-packages",
                )
            ],
        )
        # conda
        if "CONDA_PREFIX" in os.environ:
            print("CONDA", env_path)
            # Bump all prefixes up
            for key, value in filter(
                lambda i: i[0].startswith("CONDA_PREFIX_"),
                list(os.environ.items()),
            ):
                prefix = int(key[len("CONDA_PREFIX_") :])
                os.environ[f"CONDA_PREFIX_{prefix + 1}"] = value
            # Add new prefix
            old_shlvl = int(os.environ["CONDA_SHLVL"])
            os.environ["CONDA_SHLVL"] = str(old_shlvl + 1)
            os.environ["CONDA_PREFIX_1"] = os.environ["CONDA_PREFIX"]
            os.environ["CONDA_PREFIX"] = env_path
            os.environ["CONDA_DEFAULT_ENV"] = env_path
        else:
            print("VIRTUAL_ENV", env_path)
            os.environ["VIRTUAL_ENV"] = env_path
            os.environ["VIRTUAL_ENV_DIR"] = env_path

        for env_var in ["VIRTUAL_ENV", "CONDA_PREFIX"]:
            if env_var in os.environ:
                python_path = os.path.abspath(
                    os.path.join(os.environ[env_var], "bin", "python")
                )
        # Run post install hooks
        for func in self.post_activate:
            await func(self, ctx)

    async def __aexit__(self, _exc_type, _exc_value, _traceback):
        if self.old_virtual_env is not None:
            os.environ["VIRTUAL_ENV"] = self.old_virtual_env
        if self.old_virtual_env_dir is not None:
            os.environ["VIRTUAL_ENV_DIR"] = self.old_virtual_env_dir
        if self.old_path is not None:
            os.environ["PATH"] = self.old_path
        if self.old_pythonpath is not None:
            os.environ["PYTHONPATH"] = self.old_pythonpath
        # conda
        if "CONDA_PREFIX" in os.environ:
            # Decrement shell level
            os.environ["CONDA_SHLVL"] = str(int(os.environ["CONDA_SHLVL"]) - 1)
            if int(os.environ["CONDA_SHLVL"]) == 0:
                del os.environ["CONDA_SHLVL"]
            # Bump all prefixes down
            for key, value in filter(
                lambda i: i[0].startswith("CONDA_PREFIX_"),
                list(os.environ.items()),
            ):
                del os.environ[key]
                prefix = int(key[len("CONDA_PREFIX_") :])
                if prefix == 1:
                    lower_key = "CONDA_PREFIX"
                    os.environ["CONDA_PREFIX"] = value
                    os.environ["CONDA_DEFAULT_ENV"] = value
                else:
                    os.environ[f"CONDA_PREFIX_{prefix - 1}"] = value


# TODO DFFML move to dffml
ActivateVirtualEnvCommand.register_post_activate(prepend_dffml_to_path)


def prepend_dffml_to_path(self, ctx):
    # Prepend a dffml command to the path to ensure the correct
    # version of dffml always runs
    # Write out the file
    tempdir = ctx["stack"].enter_context(tempfile.TemporaryDirectory())
    dffml_path = pathlib.Path(os.path.abspath(tempdir), "dffml")
    dffml_path.write_text(
        inspect.cleandoc(
            f"""
        #!{python_path}
        import os
        import sys

        os.execv("{python_path}", ["{python_path}", "-m", "dffml", *sys.argv[1:]])
        """
        )
    )
    dffml_path.chmod(0o755)


class HTTPServerCMDDoesNotHavePortFlag(Exception):
    pass


def pipes(cmd):
    if not "|" in cmd:
        return [cmd]
    cmds = []
    j = 0
    for i, arg in enumerate(cmd):
        if arg == "|":
            cmds.append(cmd[j:i])
            j = i + 1
    cmds.append(cmd[j:])
    return cmds


async def stop_daemon(proc):
    # Send ctrl-c to daemon if running
    proc.send_signal(signal.SIGINT)
    proc.wait()


class OutputComparisionError(Exception):
    """
    Raised when the output of a command was incorrect
    """


@contextlib.contextmanager
def buf_to_fileobj(buf: Union[str, bytes]):
    """
    Given a buffer, create a temporary file and write the contents of the string
    of bytes buffer to the file. Seek to the beginning of the file. Yield the
    file object.
    """
    if isinstance(buf, str):
        buf = buf.encode()
    with tempfile.TemporaryFile() as fileobj:
        fileobj.write(buf)
        fileobj.seek(0)
        yield fileobj


class ConsoleCommand(ConsoletestCommand):
    def __init__(self, cmd: List[str]):
        super().__init__()
        self.cmd = cmd
        self.daemon_proc = None
        self.replace = None
        self.stdin = None
        self.stdin_fileobj = None
        self.stack = contextlib.ExitStack()
        self.astack = contextlib.AsyncExitStack()
        # Custom functions that can modify the command line
        self.fixups = set()

    def register_fixup(self, fixup):
        self.fixups.add(fixup)

    def unregister_fixup(self, fixup):
        self.fixups.remove(fixup)

    async def run_fixups(self, ctx):
        cmd = copy.copy(self.cmd)
        for fixup in self.fixups:
            cmd = await fixup(ctx, cmd)
        return cmd

    @classmethod
    def check(cls, cmd):
        return cls(cmd)

    async def run(self, ctx):
        # In case the command line needs the be changed. Call any fixups.
        self.cmd = await self.run_fixups(ctx)
        # Stop any things running previously registered as the same daemon
        if self.daemon is not None and self.daemon in ctx["daemons"]:
            await stop_daemon(ctx["daemons"][self.daemon].daemon_proc)
        if self.compare_output is None:
            with contextlib.ExitStack() as stack:
                self.daemon_proc = await self.ctx["run_commands"](
                    pipes(self.cmd),
                    ctx,
                    stdin=None
                    if self.stdin is None
                    else stack.enter_context(buf_to_fileobj(self.stdin)),
                    ignore_errors=self.ignore_errors,
                    daemon=bool(self.daemon),
                )
                if self.daemon is not None:
                    ctx["daemons"][self.daemon] = self
        else:
            while True:
                with contextlib.ExitStack() as stack:
                    stdout = stack.enter_context(tempfile.TemporaryFile())
                    await self.ctx["run_commands"](
                        pipes(self.cmd),
                        ctx,
                        stdin=None
                        if self.stdin is None
                        else stack.enter_context(buf_to_fileobj(self.stdin)),
                        stdout=stdout,
                        ignore_errors=self.ignore_errors,
                    )
                    stdout.seek(0)
                    stdout = stdout.read()
                    if call_compare_output(
                        self.compare_output,
                        stdout,
                        imports=self.compare_output_imports,
                    ):
                        return
                if not self.poll_until:
                    raise OutputComparisionError(
                        f"{self.cmd}: {self.compare_output}: {stdout.decode()}"
                    )
                time.sleep(0.1)

    async def __aenter__(self):
        await self.astack.__enter__()
        self.stack.__enter__()
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback):
        if self.daemon_proc is not None:
            await stop_daemon(self.daemon_proc)
        self.stack.__exit__(None, None, None)
        await self.astack.__exit__(None, None, None)


class CreateVirtualEnvCommand(ConsoleCommand):
    def __init__(self, directory: str):
        super().__init__([])
        self.directory = directory

    def __eq__(self, other: "CreateVirtualEnvCommand"):
        return bool(
            hasattr(other, "directory") and self.directory == other.directory
        )

    @classmethod
    def check(cls, cmd):
        # Handle virtualenv creation
        if (
            "-m" in cmd
            and "venv" in cmd
            and cmd[cmd.index("-m") + 1] == "venv"
        ) or (cmd[:2] == ["conda", "create"]):
            return cls(cmd[-1])

    async def run(self, ctx):
        if "CONDA_PREFIX" in os.environ:
            self.cmd = [
                "conda",
                "create",
                f"python={sys.version_info.major}.{sys.version_info.minor}",
                "-y",
                "-p",
                self.directory,
            ]
        else:
            self.cmd = ["python", "-m", "venv", self.directory]
        await super().run(ctx)


class PipNotRunAsModule(Exception):
    """
    Raised when a pip install command was not prefixed with python -m to run pip
    as a module. Pip sometimes complains when this is not done.
    """


class PipInstallCommand(ConsoleCommand):
    def __init__(self, cmd: List[str]):
        super().__init__(cmd)
        self.directories: List[str] = []
        # Ensure that we are running pip using it's module invocation
        if tuple(self.cmd[:2]) not in (("python", "-m"), ("python3", "-m")):
            raise PipNotRunAsModule(cmd)

    @classmethod
    def check(cls, cmd):
        if (
            "pip" in cmd
            and "install" in cmd
            and cmd[cmd.index("pip") + 1] == "install"
        ):
            return cls(cmd)

    async def run(self, ctx):
        await super().run(ctx)

        # Remove dataclasses. See https://github.com/intel/dffml/issues/882
        # TODO(p0,security) Audit this
        remove_dataclasses_path = (
            DFFML_ROOT
            / "scripts"
            / "tempfix"
            / "pytorch"
            / "pytorch"
            / "46930.py"
        )
        if not remove_dataclasses_path.is_file():
            return

        cmd = ["python", str(remove_dataclasses_path)]
        if "CONDA_PREFIX" in os.environ:
            cmd.append(os.environ["CONDA_PREFIX"])
        elif "VIRTUAL_ENV" in os.environ:
            cmd.append(os.environ["VIRTUAL_ENV"])
        await self.ctx["run_commands"]([cmd], ctx)

    async def __aexit__(self, _exc_type, _exc_value, _traceback):
        return


class DockerRunCommand(ConsoleCommand):
    def __init__(self, cmd: List[str]):
        name, needs_removal, cmd = self.find_name(cmd)
        super().__init__(cmd)
        self.name = name
        self.needs_removal = needs_removal
        self.stopped = False

    @classmethod
    def check(cls, cmd):
        if cmd[:2] == ["docker", "run"]:
            return cls(cmd)

    @staticmethod
    def find_name(cmd):
        """
        Find the name of the container we are starting (if starting as daemon)
        """
        name = None
        needs_removal = bool("--rm" not in cmd)
        for i, arg in enumerate(cmd):
            if arg.startswith("--name="):
                name = arg[len("--name=") :]
            elif arg == "--name" and (i + 1) < len(cmd):
                name = cmd[i + 1]
        return name, needs_removal, cmd

    def cleanup(self):
        if self.name and not self.stopped:
            subprocess.check_call(["docker", "stop", self.name])
            if self.needs_removal:
                subprocess.check_call(["docker", "rm", self.name])
        self.stopped = True

    async def __aenter__(self):
        atexit.register(self.cleanup)
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback):
        self.cleanup()


class SimpleHTTPServerCommand(ConsoleCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ts = None

    @classmethod
    def check(cls, cmd):
        if cmd[1:3] == ["-m", "http.server"]:
            return cls(cmd)

    async def __aenter__(self) -> "OperationImplementationContext":
        self.ts = None

    async def run(self, ctx):
        # Default the port to 8000
        given_port = "8000"
        # Grab port number if given
        if self.cmd[-1].isdigit():
            given_port = self.cmd[-1]
        if "--cgi" in self.cmd:
            # Start CGI server if requseted
            handler_class = http.server.CGIHTTPRequestHandler
        else:
            # Default to simple http server
            handler_class = http.server.SimpleHTTPRequestHandler
        # Specify directory if given
        directory = ctx["cwd"]
        if "--directory" in self.cmd:
            directory = self.cmd[self.cmd.index("--directory") + 1]
        # Ensure handler is relative to directory
        handler_class = functools.partial(handler_class, directory=directory)

        # Start a server with a random port
        self.ts = httptest.Server(handler_class).__enter__()
        # Map the port that was given to the port that was used
        ctx.setdefault("HTTP_SERVER", {})
        ctx["HTTP_SERVER"][given_port] = self.ts.server_port
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.ts.__exit__(None, None, None)
        self.ts = None
