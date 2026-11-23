"""TM1: Format - Format Active Process, and formatting on save."""

import sublime_plugin

from tm1pkg.commands import FormatTurboIntegratorProcess as module
from fakes import FakeView, FakeWindow


def command_names(module):
    """The command names Sublime derives from a module's command classes."""
    names = []
    for value in vars(module).values():
        is_command = isinstance(value, type) and issubclass(value, sublime_plugin.Command)
        if is_command and value.__module__ == module.__name__:
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


def saving(file_name, project):
    view = FakeView(file_name=file_name, window=FakeWindow(project) if project is not False else None)
    module.OnSaveListener().on_pre_save(view)
    return view


FORMAT_ON = {'settings': {'format_process_on_update': True}}


def test_formats_a_process_on_save_when_the_project_says_so():
    assert saving('/p/processes/Load.pro', FORMAT_ON).commands == ['format_turbo_integrator_process']
    assert saving('/p/processes/Load.pro', {'settings': {}}).commands == []


def test_saving_an_unsaved_buffer_does_nothing():
    view = saving(None, FORMAT_ON)
    assert view.commands == [] and view.erased == []


def test_saving_without_a_project_or_window_does_nothing_but_clear_errors():
    for project in (None, False):
        view = saving('/p/processes/Load.pro', project)
        assert view.commands == []
        assert view.erased == ['error']


def test_saving_other_files_leaves_their_regions_alone():
    view = saving('/p/notes.txt', FORMAT_ON)
    assert view.commands == [] and view.erased == []


def test_saving_a_rule_clears_its_errors_without_formatting():
    view = saving('/p/rules/Sales.rux', FORMAT_ON)
    assert view.commands == [] and view.erased == ['error']


def test_enabling_format_on_save_in_a_window_without_a_project_says_so():
    import sublime
    sublime.dialogs.clear()
    module.EnableFormatProcessOnSave(FakeWindow(None)).run()
    assert len(sublime.dialogs) == 1


def test_enabling_format_on_save_creates_the_settings():
    window = FakeWindow({'folders': []})
    module.EnableFormatProcessOnSave(window).run()
    assert window.project['settings']['format_process_on_update'] is True
