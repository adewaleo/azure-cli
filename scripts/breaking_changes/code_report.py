# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# From https://github.com/Azure/azure-sdk-for-python/blob/master/azure-sdk-tools/packaging_tools/code_report.py


import importlib
import inspect
import json
import logging
import pkgutil
from pathlib import Path
import subprocess
import types
import collections
from typing import Dict, Any, Optional

# Because I'm subprocessing myself, I need to do weird thing as import.
try:
    # If I'm started as a module __main__
    from .venvtools import create_venv_with_package
except ModuleNotFoundError:
    # If I'm started by my main directly
    from venvtools import create_venv_with_package


_LOGGER = logging.getLogger(__name__)

def parse_input(input_parameter):
    """From a syntax like package_name#submodule, build a package name
    and complete module name.
    """
    split_package_name = input_parameter.split('#')
    package_name = split_package_name[0]
    module_name = package_name.replace("-", ".")
    if len(split_package_name) >= 2:
        module_name = ".".join([module_name, split_package_name[1]])
    return package_name, module_name


def is_json_serializable(obj):
    try:
        json.dumps(obj)
        return True
    except:
        return False

def format_for_report(item):
    if (isinstance(item, collections.Mapping) or isinstance(item, list)) and is_json_serializable(item):
        return item  # TODO this doesn't work for AZURE_API_PROFILES as it isn't serializable.
    elif inspect.isclass(item):
        return str(item)
    elif str(item).startswith("<") and str(item).endswith(">"):
        return "instance of " + str(type(item))
    else:
        return str(item)

def create_report(module_name: str) -> Dict[str, Any]:
    module_to_generate = importlib.import_module(module_name)

    report = {}
    report["functions"] = {}
    report["classes"] = {}
    report["exceptions"] = {}
    report["others"] = {}


    for item_name in dir(module_to_generate):
        item = getattr(module_to_generate, item_name)

        # ignore modules and "private" variables
        if item_name.startswith("_") or inspect.ismodule(item):
            continue

        report_item, item_type = create_report_helper(item, module_to_generate.__name__)
        if item_type:
            report[item_type].update(report_item)

        # Other top level constants
        else:
            report["others"].update({
                item_name: format_for_report(item)
            })

    return report
    # Look for models first
    model_names = [model_name for model_name in dir(module_to_generate.models) if model_name[0].isupper()]
    for model_name in model_names:
        model_cls = getattr(module_to_generate.models, model_name)
        if hasattr(model_cls, "_attribute_map"):
            report["models"]["models"][model_name] = create_model_report(model_cls)
        elif issubclass(model_cls, Exception): # If not, might be an exception
            report["models"]["exceptions"][model_name] = create_model_report(model_cls)
        else:
            report["models"]["enums"][model_name] = create_model_report(model_cls)
    # Look for operation groups
    try:
        operations_classes = [op_name for op_name in dir(module_to_generate.operations) if op_name[0].isupper()]
    except AttributeError:
        # This guy has no "operations", this is possible (Cognitive Services). Just skip it then.
        operations_classes = []

    for op_name in operations_classes:
        op_content = {'name': op_name}
        op_cls = getattr(module_to_generate.operations, op_name)
        for op_attr_name in dir(op_cls):
            op_attr = getattr(op_cls, op_attr_name)
            if isinstance(op_attr, types.FunctionType) and not op_attr_name.startswith("_"):
                # Keep it
                func_content = create_report_from_func(op_attr)
                op_content.setdefault("functions", {})[op_attr_name] = func_content
        report.setdefault("operations", {})[op_name] = op_content

    return report

def create_report_helper(item, module_name):
    def handle_imported_module(item, item_type):
        if inspect.getmodule(item) and inspect.getmodule(item).__name__ != module_name:
            content = format_for_report(item)
            return {item.__name__: {"names": item.__name__, "type": content, "source": inspect.getmodule(item).__name__}}, item_type
        return None

    if isinstance(item, types.FunctionType) and not item.__name__.startswith("_"):
        function_type = "functions"
        result = handle_imported_module(item, function_type)
        if result:
            return result
        func_content = create_report_from_func(item)
        return {item.__name__: func_content}, function_type
    elif inspect.isclass(item) and issubclass(item, Exception):
        exception_type = "exceptions"
        result = handle_imported_module(item, exception_type)
        if result:
            return result
        ex_content = create_report_from_class(item)
        return {item.__name__: ex_content}, exception_type
    elif inspect.isclass(item):
        class_type = "classes"
        result = handle_imported_module(item, class_type)
        if result:
            return result
        cls_content = create_report_from_class(item)
        return {item.__name__: cls_content}, class_type
    # ALL others update .....,i
    return {}, None


def create_model_report(model_cls):
    result = {
        'name': model_cls.__name__,
    }
    # If _attribute_map, it's a model
    if hasattr(model_cls, "_attribute_map"):
        result['type'] = "Model"
        for attribute, conf in model_cls._attribute_map.items():
            attribute_validation = getattr(model_cls, "_validation", {}).get(attribute, {})

            result.setdefault('parameters', {})[attribute] = {
                'name': attribute,
                'properties': {
                    'type': conf['type'],
                    'required': attribute_validation.get('required', False),
                    'readonly': attribute_validation.get('readonly', False)
                }
            }
    elif issubclass(model_cls, Exception): # If not, might be an exception
        result['type'] = "Exception"
    else: # If not, it's an enum
        result['type'] = "Enum"
        result['values'] = list(model_cls.__members__)

    return result

def create_report_from_class(cls):
    cls_report = {
        'name': cls.__name__,
        'baseclasses': list(base.__name__ for base in cls.__bases__)  # check if baseclasses or baseclass order changes as it can affect method resolution order
    }

    # Handle exceptions.
    if issubclass(cls, Exception):
        return cls_report

    cls_report.update({
        'attributes': [],  # check that attribute names are the same...
        'methods': {},   # check if function names / params change
    })

    def is_builtin_function(func):
        func_types = (type(len), type([].append))
        return isinstance(func, func_types)

    if cls.__name__.lower() in ["clierror"]:
        foo = 5

    for op_attr_name in dir(cls):
        op_attr = getattr(cls, op_attr_name)
        if op_attr_name.startswith("_") and not op_attr_name == "__init__":
            continue

        # generate user_defined function or methoddescriptor info
        if is_builtin_function(op_attr):  # skip builtin functions from parent classes
            # TODO: what do we think of this? these would only change if python has a breaking change
            continue
        elif callable(op_attr) or op_attr_name == "__init__":
            func_content = create_report_from_func(op_attr)
            if func_content: # skip builtin methods (i.e. methods of types like str ResourceId inherits from str for example)
                cls_report["methods"][op_attr_name] = func_content
        else:
            cls_report["attributes"].append(op_attr_name)

    return cls_report

def create_report_from_func(func):
    func_report = {
        'name': func.__name__,
        'parameters': []
    }

    try:
        signature = inspect.signature(func)
        for parameter_name in signature.parameters:
            parameter = signature.parameters[parameter_name]

            param_dict = {'name': parameter.name}
            if parameter.default != parameter.empty:
                param_dict['default'] = format_for_report(parameter.default)

            if parameter.kind == parameter.VAR_POSITIONAL:
                param_dict['name'] = "*" + param_dict['name']
            elif parameter.kind == parameter.VAR_KEYWORD:
                param_dict['name'] = "**" + param_dict['name']

            func_report["parameters"].append(param_dict)
    except ValueError:
        func_report = {}
        pass

    return func_report

def main(input_parameter: str, version: Optional[str] = None, no_venv: bool = False, pypi: bool = False,
         last_pypi: bool = False, aggregate: bool = False):
    package_name, module_name = parse_input(input_parameter)

    if (version or pypi or last_pypi) and not no_venv:
        if version:
            versions = [version]
        else:
            _LOGGER.info(f"Download versions of {package_name} on PyPI")
            try:
                from .pypi import PyPIClient
            except ModuleNotFoundError:
                from pypi import PyPIClient

            client = PyPIClient()
            versions = [str(v) for v in client.get_ordered_versions(package_name)]
            _LOGGER.info(f"Got {versions}")
            if last_pypi:
                _LOGGER.info(f"Only keep last PyPI version")
                versions = [versions[-1]]

        for version in versions:
            _LOGGER.info(f"Installing version {version} of {package_name} in a venv")
            with create_venv_with_package([f"{package_name}=={version}"]) as venv:
                args = [
                    venv.env_exe,
                    __file__,
                    "--no-venv",
                    "--version",
                    version,
                    input_parameter
                ]
                if aggregate:
                    args.append("--aggregate-report")
                try:
                    print(args)
                    subprocess.check_call(args)
                except subprocess.CalledProcessError:
                    # If it fail, just assume this version is too old to get an Autorest report
                    _LOGGER.warning(f"Version {version} seems to be too old to build a report (probably not Autorest based)")
        # Files have been written by the subprocess
        return

    modules = find_all_core_modules(module_name)
    result = []
    aggregate_report = {}

    for module_name in modules:
        _LOGGER.info(f"Working on {module_name}")

        report = create_report(module_name)
        version = version or "latest"

        output_filename = Path(package_name) / Path("code_reports") / Path(version)

        module_for_path = get_sub_module_part(package_name, module_name)
        if module_for_path:
            output_filename /= Path(module_for_path+".json")
        else:
            output_filename /= Path(module_for_path+"__init__.json")

        if aggregate:
            aggregate_report[str(module_name)] = report
        else:
            output_filename.parent.mkdir(parents=True, exist_ok=True)

            with open(output_filename, "w") as fd:
                json.dump(report, fd, indent=2)
                _LOGGER.info(f"Report written to {output_filename}")
            result.append(output_filename)

    if aggregate:
        aggregate_path = Path(package_name) / Path("code_reports") / Path(version) / Path("report.json")
        aggregate_path.parent.mkdir(parents=True, exist_ok=True)
        with open(aggregate_path, "w") as fd:
            json.dump(aggregate_report, fd, indent=2)
            _LOGGER.info(f"Aggregate report written to {aggregate_path}")
        result = [aggregate_path]

    return result


def find_all_core_modules(module_prefix="azure.cli.core"):
    """Find all azure.cli.core modules in that module prefix.
    This actually looks for a "models" package only (not file). We could be smarter if necessary.
    """
    _LOGGER.info(f"Looking for all modules in {module_prefix}")

    result = []
    _LOGGER.debug(f"Try {module_prefix}")
    module = importlib.import_module(module_prefix)
    module.__path__
    _LOGGER.info(f"Found {module_prefix}")
    result.append(module_prefix)

    for _, sub_package, ispkg in pkgutil.iter_modules(module.__path__, module_prefix+"."):
        # if the module / pkg is in the black list skip it
        black_list = ["tests"]
        pkg_arr = sub_package.split(".")
        if pkg_arr[-1] in black_list:
            _LOGGER.info(f"Skip {sub_package}")
            continue
        if ispkg:
            result += find_all_core_modules(sub_package)
        else:
            result.append(sub_package)

    return result


# TODO: remove this method.
# def find_autorest_generated_folder(module_prefix="azure"):
#     """Find all Autorest generated code in that module prefix.
#     This actually looks for a "models" package only (not file). We could be smarter if necessary.
#     """
#     _LOGGER.info(f"Looking for Autorest generated package in {module_prefix}")
#
#     # Manually skip some namespaces for now
#     if module_prefix in ["azure.storage", "azure.servicemanagement", "azure.servicebus"]:
#         _LOGGER.info(f"Skip {module_prefix}")
#         return []
#
#     result = []
#     try:
#         _LOGGER.debug(f"Try {module_prefix}")
#         model_module = importlib.import_module(module_prefix)
#         # If not exception, we MIGHT have found it, but cannot be a file.
#         # Keep continue to try to break it, file module have no __path__
#         model_module.__path__
#         _LOGGER.info(f"Found {module_prefix}")
#         result.append(module_prefix)
#     except (ModuleNotFoundError, AttributeError):
#         # No model, might dig deeper
#         prefix_module = importlib.import_module(module_prefix)
#         for _, sub_package, ispkg in pkgutil.iter_modules(prefix_module.__path__, module_prefix+"."):
#             if ispkg:
#                 result += find_autorest_generated_folder(sub_package)
#     return result


def get_sub_module_part(package_name, module_name):
    """Assuming package is azure-mgmt-compute and module name is azure.mgmt.compute.v2018-08-01
    will return v2018-08-01
    """
    sub_module_from_package = package_name.replace("-", ".")
    if not module_name.startswith(sub_module_from_package):
        _LOGGER.warning(f"Submodule {module_name} does not start with package name {package_name}")
        return
    return module_name[len(sub_module_from_package)+1:]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description='Code fingerprint building. Excludes test modules.',
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument('package_name',
                        help='Package name.')
    parser.add_argument('--version', '-v',
                        dest='version',
                        help='The version of the package you want. By default, latest and current branch.')
    parser.add_argument('--no-venv',
                        dest='no_venv', action="store_true",
                        help="If version is provided, this will assume the current accessible package is already this version. You should probably not use it.")
    parser.add_argument('--pypi',
                        dest='pypi', action="store_true",
                        help="If provided, build report for all versions on pypi of this package.")
    parser.add_argument('--last-pypi',
                        dest='last_pypi', action="store_true",
                        help="If provided, build report for last version on pypi of this package.")
    parser.add_argument("--debug",
                        dest="debug", action="store_true",
                        help="Verbosity in DEBUG mode")
    parser.add_argument("--aggregate-report",
                        dest="aggregate", action="store_true",
                        help="Produce one report per version.")

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    main(args.package_name, args.version, args.no_venv, args.pypi, args.last_pypi, args.aggregate)