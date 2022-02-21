import sublime
import sublime_plugin

from ..utils.Format import format_procedure
from ..utils.Utils import process_to_text, view_to_process


def set_config(value):
    active_project = sublime.active_window().project_data()
    project_settings = active_project.get('settings', {})

    if not active_project:
        sublime.message_dialog(
            "Active window is not currently configured as a project.\n\nPlease go to Project -> Save Project As to continue")
        return

    project_settings['format_process_on_update'] = value

    sublime.active_window().set_project_data(active_project)


class EnableFormatProcessOnSave(sublime_plugin.WindowCommand):
    def run(self):
        set_config(True)


class DisableFormatProcessOnSave(sublime_plugin.WindowCommand):
    def run(self):
        set_config(False)


class OnSaveListener(sublime_plugin.EventListener):
    def on_pre_save(self, view):
        active_project = sublime.active_window().project_data()
        project_settings = active_project.get('settings', {})

        if not view.file_name().endswith(".pro"):
            return

        if not project_settings.get('format_process_on_update', False):
            return

        try:
            view.run_command('format_turbo_integrator_process')
        except Exception as e:
            print(e)


class FormatTurboIntegratorProcess(sublime_plugin.WindowCommand):
    def run(self):
        if not self.view.file_name().endswith(".pro"):
            return

        self.view.run_command('format_turbo_integrator_process')


class FormatTurboIntegratorProcessCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        process = view_to_process(self.view, None)

        process.prolog_procedure = format_procedure(process.prolog_procedure)
        process.metadata_procedure = format_procedure(process.metadata_procedure)
        process.data_procedure = format_procedure(process.data_procedure)
        process.epilog_procedure = format_procedure(process.epilog_procedure)

        text = process_to_text(process)

        text = text.replace('\r\n', '\n')

        selections = [sel for sel in self.view.sel()]

        self.view.erase(edit, sublime.Region(0, self.view.size()))
        self.view.insert(edit, 0, text)

        self.view.sel().clear()

        for sel in selections:
            self.view.sel().add(sel)
