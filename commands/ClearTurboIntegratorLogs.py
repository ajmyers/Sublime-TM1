import sublime
import sublime_plugin

from pelle.Session import get_session


class ClearTurboIntegratorLogs(sublime_plugin.WindowCommand):
    def run(self):
        window = sublime.active_window()
        session = get_session(window)
        session.clear_turbo_integrator_logs()
