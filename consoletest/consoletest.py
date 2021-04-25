from .commands import *


class Consoletest:
    def __init__(
        self,
        commands: Optional[List["ConsoletestCommand"]] = None,
        default_command: Optional["ConsoletestCommand"] = None,
    ):
        # Command class to run if none other match cmd line argument list
        self.default_command = default_command if default_command is None else ConsoleCommand
        # Initialize to all builtin commands if no list given
        self.commands = commands if commands else [
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
