import os
import io
import enum
import codecs
import shutil
import inspect
import pathlib
import tempfile
import contextlib
from typing import (
    Any,
    Dict,
    List,
    Union,
    Tuple,
    Optional,
)

from .commands import ConsoletestCommand, ConsoleCommand, call_replace
from .util import copyfile
from .parser import Node, parse_commands
from .commands import *


class Consoletest:
    LITERALINCLUDE_OPTION_SPEC = {
        "filepath": "unchanged_required",
        "test": "flag",
    }
    CODE_BLOCK_OPTION_SPEC = {
        "filepath": "unchanged_required",
        "replace": "unchanged_required",
        "poll-until": "flag",
        "compare-output": "unchanged_required",
        "compare-output-imports": "unchanged_required",
        "ignore-errors": "flag",
        "daemon": "unchanged_required",
        "test": "flag",
        "stdin": "unchanged_required",
        "overwrite": "flag",
    }

    def __init__(
        self,
        commands: Optional[List[ConsoletestCommand]] = None,
        default_command: Optional[ConsoletestCommand] = None,
        node_handlers = None,
    ):
        # Command class to run if none other match cmd line argument list
        self.default_command = (
            default_command if default_command is None else ConsoleCommand
        )
        # Initialize to all commands registered as entrypoints if no list given.
        self.commands = commands
        if self.commands is None:
            self.commands = [
                entry_point.load()
                for entry_point in importlib.metadata.entry_points().select(
                    group="consoletest.command"
                )
            ]
        # Remove default command from list of commands if it's in the list
        if self.default_command in self.commands:
            self.commands.remove(self.default_command)
        # Map node types to how their handlers
        # node["consoletestnodetype"] in self.node_handlers "consoletest-literalinclude":
        # node["consoletestnodetype"] == "consoletest-file":
        # node["consoletestnodetype"] == "consoletest":
        self.node_handlers = node_handlers if isinstance(node_handlers, dict) else {
            "consoletest-literalinclude": self.literalinclude_to_dict,
            "consoletest-file": self.,
            "consoletest": ,
        }

    def build_command(self, cmd):
        if not cmd:
            raise ValueError("Empty command")
        # Check all registered commands and instantiate an instance of the
        # command class to manage execution of the command if the command class
        # is applicable to the cmd line arguments given.
        for command_cls in self.commands:
            command = command_cls.check(cmd)
        # Instantiate default command when none in the list are applicable.
        return cls.default_command(cmd)

    def literalinclude_to_dict(
        self,
        content: List[str],
        options: Dict[str, Union[bool, str]],
        node: Dict[str, Any],
    ) -> Dict[str, Any]:
        if node is None:
            node = {}

        if "source" not in node:
            raise ValueError('node must have "source" property')

        if "test" in options:
            node["consoletestnodetype"] = self.NODE_TYPE_LITERALINCLUDE
            node["lines"] = options.get("lines", None)
            node["filepath"] = options.get(
                "filepath", os.path.basename(node["source"])
            ).split("/")

        return node

    def code_block_to_dict(
        self,
        content: List[str],
        options: Dict[str, Union[bool, str]],
        *,
        node: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if node is None:
            node = {}

        if "filepath" in options:
            node["consoletestnodetype"] = "consoletest-file"
            node["content"] = content
            node["filepath"] = options["filepath"].split("/")
            node["overwrite"] = bool("overwrite" in options)
        elif "test" in options:
            node.setdefault("language", "console")
            node["consoletestnodetype"] = "consoletest"
            node["consoletest_commands"] = list(
                map(self.build_command, parse_commands(content))
            )

            node["consoletest_commands_replace"] = options.get("replace", None)
            for command in node["consoletest_commands"]:
                command.poll_until = bool("poll-until" in options)
                command.compare_output = options.get("compare-output", None)
                command.compare_output_imports = options.get(
                    "compare-output-imports", None
                )
                if command.poll_until and command.compare_output is None:
                    raise ValueError(
                        "Cannot set poll-until without compare-output"
                    )
                command.ignore_errors = bool("ignore-errors" in options)
                if "stdin" in options:
                    command.stdin = codecs.getdecoder("unicode_escape")(
                        options["stdin"]
                    )[0]

            # Last command to be run is a daemon
            if "daemon" in options:
                node["consoletest_commands"][-1].daemon = options["daemon"]

        return node

    def nodes_to_test(nodes: List[Node]) -> List[Node]:
        """
        List of nodes to subset of that list which have the ``:test::`` option.
        """
        subset_nodes = []

        for node in nodes:
            if not node.options.get("test", False):
                continue
            if node.directive == "code-block":
                subset_nodes.append(
                    self.code_block_to_dict(
                        node.content, node.options, node=node.node
                    )
                )
            elif node.directive == "literalinclude":
                subset_nodes.append(
                    self.literalinclude_to_dict(
                        node.content, node.options, node.node
                    )
                )

        return subset_nodes

    async def run_nodes(
        self,
        repo_root_dir: Union[str, pathlib.Path],
        docs_root_dir: Union[str, pathlib.Path],
        nodes: List[Dict[str, Any]],
        *,
        setup: Optional[List[ConsoletestCommand]] = None,
    ) -> None:
        # Ensure pathlib objects
        repo_root_dir = pathlib.Path(repo_root_dir).resolve()
        docs_root_dir = pathlib.Path(docs_root_dir).resolve()
        # Create an async exit stack
        async with contextlib.AsyncExitStack() as astack:
            tempdir = stack.enter_context(tempfile.TemporaryDirectory())

            ctx = {
                "root": str(repo_root_dir),
                "docs": str(docs_root_dir),
                "cwd": tempdir,
                "stack": stack,
                "astack": astack,
                "daemons": {},
                # Items in this context that must are not serializable
                "no_serialize": {"stack", "astack", "daemons"},
            }

            # Create a virtualenv for every document
            if setup is not None:
                await setup(ctx)

            for node in nodes:  # type: Element
                if node["consoletestnodetype"] in self.node_handlers:
                    await self.node_handlers[node["consoletestnodetype"]](ctx, node)
                else:
                    raise NotImplementedError("\'consoletestnodetype\' not found in node_handlers")

        def file(self, ctx, node):
            print()
            filepath = pathlib.Path(ctx["cwd"], *node["filepath"])

            if not filepath.parent.is_dir():
                filepath.parent.mkdir(parents=True)

            if node["overwrite"] and filepath.is_file():
                print("Overwriting", ctx, filepath)
                mode = "wt"
            else:
                print("Writing", ctx, filepath)
                mode = "at"

            with open(filepath, mode) as outfile:
                outfile.seek(0, io.SEEK_END)
                outfile.write("\n".join(node["content"]) + "\n")

            print(filepath.read_text(), end="")
            print()

        def consoletest(self, ctx, node):
            if node["consoletest_commands_replace"] is not None:
                for command, new_cmd in zip(
                    node["consoletest_commands"],
                    call_replace(
                        node["consoletest_commands_replace"],
                        list(
                            map(
                                lambda command: command.cmd
                                if isinstance(command, ConsoleCommand)
                                else [],
                                node["consoletest_commands"],
                            )
                        ),
                        ctx,
                    ),
                ):
                    if isinstance(command, ConsoleCommand):
                        command.cmd = new_cmd
            for command in node["consoletest_commands"]:
                print()
                print("Running", ctx, command)
                print()
                await astack.enter_async_context(command)
                await command.run(ctx)

        def literalinclude(self, ctx):
            lines = node.get("lines", None)
            if lines is not None:
                lines = tuple(map(int, lines.split("-")))

            # Handle navigating out of the docs_root_dir
            if node["source"].startswith("/.."):
                node["source"] = node["source"][1:]

            src = os.path.join(str(docs_root_dir), node["source"])
            dst = os.path.join(ctx["cwd"], *node["filepath"])

            print()
            print("Copying", ctx, src, dst, lines)

            copyfile(src, dst, lines=lines)
            print(pathlib.Path(dst).read_text(), end="")
            print()
