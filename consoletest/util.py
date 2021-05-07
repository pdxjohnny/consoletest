import os
import io
import sys
import shutil
import pathlib
import contextlib
from typing import Any, Union, Tuple, Optional


@contextlib.contextmanager
def chdir(new_path):
    """
    Context manager to change directory.
    """
    old_path = os.getcwd()
    os.chdir(new_path)
    try:
        yield
    finally:
        os.chdir(old_path)


def copyfile(
    src: str, dst: str, *, lines: Optional[Union[int, Tuple[int, int]]] = None
) -> None:
    """
    Copy source file to destination. If line numbers are given, either a single
    int for a single line, or a tuple of start line and end line, then append
    those lines from the source to the destination.
    """
    dst_path = pathlib.Path(dst)
    if not dst_path.parent.is_dir():
        dst_path.parent.mkdir(parents=True)

    if not lines:
        shutil.copyfile(src, dst)
        return

    with open(src, "rt") as infile, open(dst, "at") as outfile:
        outfile.seek(0, io.SEEK_END)
        for i, line in enumerate(infile):
            # Line numbers start at 1
            i += 1
            if len(lines) == 1 and i == lines[0]:
                outfile.write(line)
                break
            elif i >= lines[0] and i <= lines[1]:
                outfile.write(line)
            elif i > lines[1]:
                break


MAKE_POLL_UNTIL_TEMPLATE = """
import sys
{imports}

func = lambda stdout: {func}

sys.exit(int(not func(sys.stdin.buffer.read())))
"""


def call_compare_output(func, stdout, *, imports: Optional[str] = None):
    with tempfile.NamedTemporaryFile() as fileobj, tempfile.NamedTemporaryFile() as stdin:
        fileobj.write(
            MAKE_POLL_UNTIL_TEMPLATE.format(
                func=func,
                imports="" if imports is None else "import " + imports,
            ).encode()
        )
        fileobj.seek(0)
        stdin.write(stdout.encode() if isinstance(stdout, str) else stdout)
        stdin.seek(0)
        return_code = subprocess.call(
            [sys.executable, fileobj.name], stdin=stdin
        )
        return bool(return_code == 0)


MAKE_REPLACE_UNTIL_TEMPLATE = """
import sys
import json
import pathlib

cmds = json.loads(pathlib.Path(sys.argv[1]).read_text())
ctx = json.loads(pathlib.Path(sys.argv[2]).read_text())

{func}

print(json.dumps(cmds))
"""


def call_replace(
    func: str, cmds: List[List[str]], ctx: Dict[str, Any]
) -> List[List[str]]:
    with contextlib.ExitStack() as stack:
        # Write out Python script
        python_fileobj = stack.enter_context(tempfile.NamedTemporaryFile())
        python_fileobj.write(
            MAKE_REPLACE_UNTIL_TEMPLATE.format(func=func).encode()
        )
        python_fileobj.seek(0)
        # Write out command
        cmd_fileobj = stack.enter_context(tempfile.NamedTemporaryFile())
        cmd_fileobj.write(json.dumps(cmds).encode())
        cmd_fileobj.seek(0)
        # Write out context
        ctx_fileobj = stack.enter_context(tempfile.NamedTemporaryFile())
        ctx_serializable = ctx.copy()
        for remove in list(ctx["no_serialize"]) + ["no_serialize"]:
            if remove in ctx_serializable:
                del ctx_serializable[remove]
        ctx_fileobj.write(json.dumps(ctx_serializable).encode())
        ctx_fileobj.seek(0)
        # Python file modifies command and json.dumps result to stdout
        return json.loads(
            subprocess.check_output(
                [
                    sys.executable,
                    python_fileobj.name,
                    cmd_fileobj.name,
                    ctx_fileobj.name,
                ],
            )
        )
