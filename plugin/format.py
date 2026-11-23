"""TM1: Format - Format Active Process, and formatting processes on save.

Only the code of the four procedures is formatted: the rest of the file stays as it was, byte for
byte. 0.2.x parsed the whole file into a TM1py Process and wrote all of it back.
"""

import sublime
import sublime_plugin

from ..core.formatter import format_procedure
from ..core.process_file import format_procedures


def is_process(view):
    return (view.file_name() or '').endswith('.pro')


def set_config(window, value):
    project = window.project_data()
    if not project:
        sublime.message_dialog('Active window is not currently configured as a project.\n\n'
                               'Please go to Project -> Save Project As to continue')
        return
    project.setdefault('settings', {})['format_process_on_update'] = value
    window.set_project_data(project)


class EnableFormatProcessOnSave(sublime_plugin.WindowCommand):
    def run(self):
        set_config(self.window, True)


class DisableFormatProcessOnSave(sublime_plugin.WindowCommand):
    def run(self):
        set_config(self.window, False)


class OnSaveListener(sublime_plugin.EventListener):
    def on_pre_save(self, view):
        if not is_process(view):
            return
        window = view.window()
        project = window.project_data() if window else None
        if (project or {}).get('settings', {}).get('format_process_on_update', False):
            view.run_command('format_turbo_integrator_process')


class FormatTurboIntegratorProcessCommand(sublime_plugin.TextCommand):
    def is_enabled(self):
        return is_process(self.view)

    def run(self, edit):
        text = self.view.substr(sublime.Region(0, self.view.size()))
        formatted = format_procedures(text, format_procedure)
        if formatted == text:
            return
        selections = list(self.view.sel())
        self.view.replace(edit, sublime.Region(0, self.view.size()), formatted)
        self.view.sel().clear()
        for selection in selections:
            self.view.sel().add(selection)
