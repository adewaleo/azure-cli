# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
from azure.cli.command_modules.acr._docker_utils import get_login_credentials
from azure.cli.command_modules.acr._errors import CONNECTIVITY_AAD_LOGIN_ERROR


def acr_pull(cmd, client, allow_all=None, allow_path_traversal=None, config=None,
             keep_old_files=None, media_type=None,
             destination=None, password=None, username=None):
    pass

def acr_push(cmd, client):
    pass