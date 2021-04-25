import os
import io
import codecs
import shutil
import inspect
import pathlib
import contextlib
from typing import (
    Any,
    Dict,
    List,
    Union,
    Tuple,
    Optional,
)

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
    ):
        # Command class to run if none other match cmd line argument list
        self.default_command = (
            default_command if default_command is None else ConsoleCommand
        )
        # Initialize to all builtin commands if no list given. sys.modules is a
        # dict where the keys are the full paths of modules. For example,
        # __name__ should be consoletest.consoletest (unless we change the
        # name). We chop of the last part, which is this filename, and replace
        # it with "commands" which is where we import the commands from at the
        # top of this file. This is just in case we change the name from
        # "consoletest" to something else later. So it should end up looking in
        # sys.modules["consoletest.commands"] for commands.
        self.commands = commands
        if self.commands is None:
            self.commands = [
                command
                for command in sys.modules[
                    ".".join(__name__.split(".")[:-1] + ["commands"])
                ]
                if inspect.isclass(command)
                and issubclass(command, ConsoletestCommand)
            ]
        # Remove default command from list of commands if it's in the list
        if self.default_command in self.commands:
            self.commands.remove(self.default_command)

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
            node["consoletestnodetype"] = "consoletest-literalinclude"
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
