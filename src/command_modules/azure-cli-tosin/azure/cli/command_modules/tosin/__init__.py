# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core import AzCommandsLoader

from azure.cli.command_modules.tosin._help import helps  # pylint: disable=unused-import


class TosinCommandsLoader(AzCommandsLoader):

    def __init__(self, cli_ctx=None):
        from azure.cli.core.commands import CliCommandType
        tosin_custom = CliCommandType(operations_tmpl='azure.cli.command_modules.example.custom#{}')

        super(TosinCommandsLoader, self).__init__(cli_ctx=cli_ctx,
                                                  min_profile='2017-03-10-profile',
                                                  custom_command_type=tosin_custom)

    def load_command_table(self, args):
        from azure.cli.command_modules.tosin.commands import load_command_table
        load_command_table(self, args)
        return self.command_table

    def load_arguments(self, command):
        from azure.cli.command_modules.tosin._params import load_arguments
        load_arguments(self, command)


COMMAND_LOADER_CLS = TosinCommandsLoader
