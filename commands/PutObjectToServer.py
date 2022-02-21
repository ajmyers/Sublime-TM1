import sublime
import sublime_plugin

from ..utils.Session import get_session


class PutObjectToServer(sublime_plugin.WindowCommand):
    def run(self):
        window = sublime.active_window()
        view = window.active_view()
        session = get_session(window)
        session.update_object(view)
