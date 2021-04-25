import os
import io
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
