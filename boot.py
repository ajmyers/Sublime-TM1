# Sublime Text loads this module and registers the command and listener classes it finds in its
# namespace, so each one the package defines is imported here.
# ruff: noqa: E402 (the imports below need the libraries in include/ on sys.path first)

import os
import sys

base_path = os.path.split(os.path.realpath(__file__))[0]

# The libraries copied into include/. They go once the package's dependencies come from Package
# Control (#22); until then they're put first on the plugin host's shared sys.path.
for path in ['wcwidth', 'prettytable/src/prettytable', 'TM1py', 'mdxpy', 'urllib3/src', 'requests',
             'charset_normalizer', 'idna', 'ijson', 'pytz/src', 'pyyaml/lib']:
    sys.path.insert(0, os.path.join(base_path, 'include', *path.split('/')))

from .plugin.python_host import work_around_missing_sysconfigdata

work_around_missing_sysconfigdata()

from .plugin import gateway
from .plugin.completions import ProjectCompletions
from .plugin.console import (
    DisplayTm1OpsConsole,
    KillTm1ThreadCommand,
    RefreshTm1OpsConsoleCommand,
    Tm1SetPanelTextCommand,
    Tm1TailServerLogCommand,
)
from .plugin.credentials import Tm1ReplaceInputTextCommand
from .plugin.diagnostics import Tm1DiagnosticsListener
from .plugin.format import (
    DisableFormatProcessOnSave,
    EnableFormatProcessOnSave,
    FormatTurboIntegratorProcessCommand,
    OnSaveListener,
)
from .plugin.get import GetObjectsFromServer
from .plugin.put import PutObjectToServer
from .plugin.run import ClearTurboIntegratorLogs, RunTurboIntegratorProcess
from .plugin.setup import CreateNewTm1Project, Tm1SignOutCommand, UpdateTm1Project

__all__ = [
    'ClearTurboIntegratorLogs',
    'CreateNewTm1Project',
    'DisableFormatProcessOnSave',
    'DisplayTm1OpsConsole',
    'EnableFormatProcessOnSave',
    'FormatTurboIntegratorProcessCommand',
    'GetObjectsFromServer',
    'KillTm1ThreadCommand',
    'OnSaveListener',
    'ProjectCompletions',
    'PutObjectToServer',
    'RefreshTm1OpsConsoleCommand',
    'RunTurboIntegratorProcess',
    'Tm1DiagnosticsListener',
    'Tm1SetPanelTextCommand',
    'Tm1SignOutCommand',
    'Tm1TailServerLogCommand',
    'Tm1ReplaceInputTextCommand',
    'UpdateTm1Project',
    'plugin_unloaded',
]


def plugin_unloaded():
    # Close TM1 sessions and stop the gateway's threads, and forget passwords, when Sublime
    # unloads the package (quitting, upgrading, disabling it)
    gateway.shutdown()
