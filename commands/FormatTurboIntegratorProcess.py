import sublime
import sublime_plugin

from pelle.Format import format_procedure
from pelle.Utils import process_to_text, view_to_process

TM1_EXTENSIONS = ('.pro', '.rux')


def is_process(view):
    file_name = view.file_name()
    return bool(file_name) and file_name.endswith('.pro')


def is_tm1_file(view):
    file_name = view.file_name()
    return bool(file_name) and file_name.endswith(TM1_EXTENSIONS)


def set_config(window, value):
    project = window.project_data()
    if not project:
        sublime.message_dialog(
            "Active window is not currently configured as a project.\n\n"
            "Please go to Project -> Save Project As to continue")
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
        if not is_tm1_file(view):
            return

        view.erase_regions('error')

        window = view.window()
        project = window.project_data() if window else None
        if not is_process(view) or not (project or {}).get('settings', {}).get('format_process_on_update', False):
            return

        view.run_command('format_turbo_integrator_process')


class FormatTurboIntegratorProcessCommand(sublime_plugin.TextCommand):
    def is_enabled(self):
        return is_process(self.view)

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
