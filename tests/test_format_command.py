"""TM1: Format - Format Active Process, and formatting on save."""

import sublime_plugin

from commands import FormatTurboIntegratorProcess as module
from fakes import FakeView


def command_names(module):
    """The command names Sublime derives from a module's command classes."""
    names = []
    for value in vars(module).values():
        if isinstance(value, type) and issubclass(value, sublime_plugin.Command) and value.__module__ == module.__name__:
            name = value.__name__
            name = name[:-len('Command')] if name.endswith('Command') else name
            names.append(''.join('_' + c.lower() if c.isupper() else c for c in name).lstrip('_'))
    return names


def test_each_command_name_is_defined_once():
    names = command_names(module)
    assert sorted(names) == sorted(set(names))
    assert 'format_turbo_integrator_process' in names


def test_format_is_enabled_for_processes_only():
    command = module.FormatTurboIntegratorProcessCommand
    assert command(FakeView(file_name='/p/processes/Load.pro')).is_enabled()
    assert not command(FakeView(file_name='/p/rules/Sales.rux')).is_enabled()
    assert not command(FakeView(file_name=None)).is_enabled()
