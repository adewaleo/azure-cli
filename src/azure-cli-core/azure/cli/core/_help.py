# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from __future__ import print_function

from knack.help import (HelpFile as KnackHelpFile, CommandHelpFile as KnackCommandHelpFile,
                        GroupHelpFile as KnackGroupHelpFile, ArgumentGroupRegistry as KnackArgumentGroupRegistry,
                        HelpExample as KnackHelpExample, HelpParameter as KnackHelpParameter,
                        HelpAuthoringException, CLIHelp)

from knack.log import get_logger
from knack.util import CLIError

from azure.cli.core.commands import ExtensionCommandSource

logger = get_logger(__name__)

PRIVACY_STATEMENT = """
Welcome to Azure CLI!
---------------------
Use `az -h` to see available commands or go to https://aka.ms/cli.

Telemetry
---------
The Azure CLI collects usage data in order to improve your experience.
The data is anonymous and does not include commandline argument values.
The data is collected by Microsoft.

You can change your telemetry settings with `az configure`.
"""

WELCOME_MESSAGE = r"""
     /\
    /  \    _____   _ _  ___ _
   / /\ \  |_  / | | | \'__/ _\
  / ____ \  / /| |_| | | |  __/
 /_/    \_\/___|\__,_|_|  \___|


Welcome to the cool new Azure CLI!

Use `az --version` to display the current version.
Here are the base commands:
"""


class AzCliHelp(CLIHelp):

    def __init__(self, cli_ctx):
        super(AzCliHelp, self).__init__(cli_ctx,
                                        privacy_statement=PRIVACY_STATEMENT,
                                        welcome_message=WELCOME_MESSAGE,
                                        command_help_cls=CliCommandHelpFile,
                                        group_help_cls=CliGroupHelpFile,
                                        help_cls=CliHelpFile)
        from knack.help import HelpObject

        # TODO: This workaround is used to avoid a bizarre bug in Python 2.7. It
        # essentially reassigns Knack's HelpObject._normalize_text implementation
        # with an identical implemenation in Az. For whatever reason, this fixes
        # the bug in Python 2.7.
        @staticmethod
        def new_normalize_text(s):
            if not s or len(s) < 2:
                return s or ''
            s = s.strip()
            initial_upper = s[0].upper() + s[1:]
            trailing_period = '' if s[-1] in '.!?' else '.'
            return initial_upper + trailing_period

        HelpObject._normalize_text = new_normalize_text  # pylint: disable=protected-access

        self._register_help_loaders()


    @staticmethod
    def _print_extensions_msg(help_file):
        if help_file.type != 'command':
            return
        if isinstance(help_file.command_source, ExtensionCommandSource):
            logger.warning(help_file.command_source.get_command_warn_msg())
            if help_file.command_source.preview:
                logger.warning(help_file.command_source.get_preview_warn_msg())

    def _print_detailed_help(self, cli_name, help_file):
        AzCliHelp._print_extensions_msg(help_file)
        super(AzCliHelp, self)._print_detailed_help(cli_name, help_file)

    def _register_help_loaders(self):
        import azure.cli.core._help_loaders as help_loaders
        import inspect

        def is_loader_cls(cls):
            return inspect.isclass(cls) and issubclass(cls, help_loaders.BaseHelpLoader)

        versioned_loaders = {}
        for cls_name, loader_cls in inspect.getmembers(help_loaders, is_loader_cls):
            loader = loader_cls(self)
            versioned_loaders[cls_name] = loader

        self.versioned_loaders = versioned_loaders

class CliHelpFile(KnackHelpFile):

    def __init__(self, help_ctx, delimiters):
        # Each help file (for a command or group) has a version denoting the source of its data.
        self.yaml_help_version = 0
        super(CliHelpFile, self).__init__(help_ctx, delimiters)
        self.links = []

    def _should_include_example(self, ex):
        min_profile = ex.get('min_profile')
        max_profile = ex.get('max_profile')
        if min_profile or max_profile:
            from azure.cli.core.profiles import supported_api_version, PROFILE_TYPE
            # yaml will load this as a datetime if it's a date, we need a string.
            min_profile = str(min_profile) if min_profile else None
            max_profile = str(max_profile) if max_profile else None
            return supported_api_version(self.help_ctx.cli_ctx, resource_type=PROFILE_TYPE,
                                         min_api=min_profile, max_api=max_profile)
        return True

    # Needs to override base implementation to exclude unsupported examples.
    def _load_from_data(self, data):
        super(CliHelpFile, self)._load_from_data(data)
        self.examples = []  # clear examples set by knack
        if 'examples' in data:
            self.examples = []
            for d in data['examples']:
                if self._should_include_example(d):
                    self.examples.append(HelpExample(d))

    def load(self, options):
        ordered_loaders = sorted(self.help_ctx.versioned_loaders.values(), key=lambda ldr: ldr.VERSION)
        for loader in ordered_loaders:
            loader.load(self, options)


class CliGroupHelpFile(KnackGroupHelpFile, CliHelpFile):
    def __init__(self, help_ctx, delimiters, parser):
        super(CliGroupHelpFile, self).__init__(help_ctx, delimiters, parser)

    def load(self, options):
        # forces class to use this load method even if KnackGroupHelpFile overrides CliHelpFile's method.
        CliHelpFile.load(self, options)


class CliCommandHelpFile(KnackCommandHelpFile, CliHelpFile):

    def __init__(self, help_ctx, delimiters, parser):
        self.command_source = getattr(parser, 'command_source', None)
        self.parameters = []

        for action in [a for a in parser._actions if a.help != argparse.SUPPRESS]:  # pylint: disable=protected-access
            if action.option_strings:
                self._add_parameter_help(action)
            else:
                # use metavar for positional parameters
                param_kwargs = {
                    'name_source': [action.metavar or action.dest],
                    'deprecate_info': getattr(action, 'deprecate_info', None),
                    'description': action.help,
                    'choices': action.choices,
                    'required': False,
                    'default': None,
                    'group_name': 'Positional'
                }
                self.parameters.append(HelpParameter(**param_kwargs))

        help_param = next(p for p in self.parameters if p.name == '--help -h')
        help_param.group_name = 'Global Arguments'

    def _load_from_data(self, data):
        super(CliCommandHelpFile, self)._load_from_data(data)

        if isinstance(data, str) or not self.parameters or not data.get('parameters'):
            return

        loaded_params = []
        loaded_param = {}
        for param in self.parameters:
            loaded_param = next((n for n in data['parameters'] if n['name'] == param.name), None)
            if loaded_param:
                param.update_from_data(loaded_param)
            loaded_params.append(param)

        self.parameters = loaded_params

    def load(self, options):
        # forces class to use this load method even if KnackGroupHelpFile overrides CliHelpFile's method.
        CliHelpFile.load(self, options)

class ArgumentGroupRegistry(KnackArgumentGroupRegistry):  # pylint: disable=too-few-public-methods

    def __init__(self, group_list):

        super(ArgumentGroupRegistry, self).__init__(group_list)
        self.priorities = {
            None: 0,
            'Resource Id Arguments': 1,
            'Generic Update Arguments': 998,
            'Global Arguments': 1000,
        }
        priority = 2
        # any groups not already in the static dictionary should be prioritized alphabetically
        other_groups = [g for g in sorted(list(set(group_list))) if g not in self.priorities]
        for group in other_groups:
            self.priorities[group] = priority
            priority += 1


class HelpExample(KnackHelpExample):  # pylint: disable=too-few-public-methods

    def __init__(self, _data):
        _data['name'] = _data.get('name', '')
        _data['text'] = _data.get('text', '')
        super(HelpExample, self).__init__(_data)

        self.command = _data.get('command', '')
        self.description = _data.get('description', '')

        self.min_profile = _data.get('min_profile', '')
        self.max_profile = _data.get('max_profile', '')

        self.text = "{}\n{}".format(self.description, self.command) if self.description else self.command


class HelpParameter(KnackHelpParameter):  # pylint: disable=too-many-instance-attributes

    def __init__(self, **kwargs):
        super(HelpParameter, self).__init__(**kwargs)
        self.raw_value_sources = []

    def update_from_data(self, data):
        if self.name != data.get('name'):
            raise HelpAuthoringException(u"mismatched name {} vs. {}"
                                         .format(self.name,
                                                 data.get('name')))

        if data.get('summary'):
            self.short_summary = data.get('summary')

        if data.get('description'):
            self.long_summary = data.get('description')

        if data.get('value-sources'):
            self.raw_value_sources = data.get('value-sources')
            for value_source in self.raw_value_sources:
                val_str = self._raw_value_source_to_string(value_source)
                if val_str:
                    self.value_sources.append(val_str)