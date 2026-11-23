"""TM1: Format - Format Active Process, and formatting on save."""

import sublime
import sublime_plugin

import core_samples
from fakes import FakeView, FakeWindow
from tm1pkg.core.formatter import format_procedure
from tm1pkg.core.process_file import format_procedures, process_to_text
from tm1pkg.plugin import diagnostics
from tm1pkg.plugin import format as module


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


UNFORMATTED = process_to_text(core_samples.parameters_and_variables()).replace(
    "IF(pYear @= '');\n   ProcessQuit;\nENDIF;", "if(pYear@='');\nprocessquit;\nendif;")


def test_formats_only_the_code_of_the_procedures():
    formatted = format_procedures(UNFORMATTED, format_procedure)
    before, after = UNFORMATTED.split('\n'), formatted.split('\n')
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(before) == len(after)
    assert [after[i] for i in changed] == ["IF(pYear @= '');", '   PROCESSQUIT;', 'ENDIF;',
                                           "CELLPUTN(vValue, 'Sales', vRegion, pYear, 'Amount');"]
    assert all('### ' not in before[i] for i in changed)


def test_keeps_windows_line_endings_and_leaves_a_formatted_file_alone():
    crlf = UNFORMATTED.replace('\n', '\r\n')
    formatted_crlf = format_procedures(crlf, format_procedure)
    assert formatted_crlf.count('\r\n') == crlf.count('\r\n')
    formatted = format_procedures(UNFORMATTED, format_procedure)
    assert format_procedures(formatted, format_procedure) == formatted


class EditableView(FakeView):
    def __init__(self, text, file_name):
        super().__init__(text, file_name)
        self.selections = [sublime.Region(5)]

    def sel(self):
        view = self

        class Selection(list):
            def clear(self):
                view.selections = []

            def add(self, region):
                view.selections.append(region)

        return Selection(self.selections)

    def replace(self, edit, region, text):
        self.text = self.text[:region.begin()] + text + self.text[region.end():]


def test_the_command_rewrites_the_view_and_keeps_the_cursor():
    view = EditableView(UNFORMATTED, '/p/processes/Load Sales.pro')
    module.FormatTurboIntegratorProcessCommand(view).run(None)
    assert view.text == format_procedures(UNFORMATTED, format_procedure)
    assert view.selections == [sublime.Region(5)]


def saving(file_name, project):
    view = FakeView(file_name=file_name, window=FakeWindow(project) if project is not False else None)
    module.OnSaveListener().on_pre_save(view)
    diagnostics.Tm1DiagnosticsListener().on_pre_save(view)
    return view


FORMAT_ON = {'settings': {'format_process_on_update': True}}


def test_formats_a_process_on_save_when_the_project_says_so():
    assert saving('/p/processes/Load.pro', FORMAT_ON).commands == ['format_turbo_integrator_process']
    assert saving('/p/processes/Load.pro', {'settings': {}}).commands == []


def test_saving_an_unsaved_buffer_or_another_file_does_nothing():
    for name in (None, '/p/notes.txt'):
        view = saving(name, FORMAT_ON)
        assert view.commands == [] and view.erased == []


def test_saving_without_a_project_or_window_only_clears_errors():
    for project in (None, False):
        view = saving('/p/processes/Load.pro', project)
        assert view.commands == [] and diagnostics.KEY in view.erased


def test_saving_a_rule_clears_its_errors_without_formatting():
    view = saving('/p/rules/Sales.rux', FORMAT_ON)
    assert view.commands == [] and diagnostics.KEY in view.erased and diagnostics.LEGACY_KEY in view.erased


def test_enabling_format_on_save_in_a_window_without_a_project_says_so():
    sublime.dialogs.clear()
    module.EnableFormatProcessOnSave(FakeWindow(None)).run()
    assert len(sublime.dialogs) == 1


def test_enabling_format_on_save_creates_the_settings():
    window = FakeWindow({'folders': []})
    module.EnableFormatProcessOnSave(window).run()
    assert window.project['settings']['format_process_on_update'] is True
