import sublime
import sublime_plugin

from pelle.Pelle import get_session


class GetObjectsFromServer(sublime_plugin.WindowCommand):
    def run(self):
        window = sublime.active_window()
        session = get_session(window)
        session.refresh_objects()
