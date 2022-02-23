import threading
import time

import sublime
import sublime_plugin

from pelle.Session import get_session

DEFAULT_REFRESH = 2.5


class DisplayTm1OpsConsole(sublime_plugin.WindowCommand):

    def run(self):
        self.active_project = sublime.active_window().project_data()
        self.project_settings = self.active_project['settings']
        self.session = get_session(sublime.active_window())

        # Get instance name
        window_name = 'Console'

        # Create Output Window
        self.output = self.window.create_output_panel(window_name)
        self.output.run_command('erase_view')
        self.window.run_command('show_panel', {'panel': 'output.{}'.format(window_name)})

        self.output.set_read_only(True)

        t = threading.Thread(target=self.run_refresh, daemon=True)
        t.start()

    def run_refresh(self):
        if 'ConsoleRefreshTime' in self.project_settings:
            refresh_time = self.project_settings['ConsoleRefreshTime']
        else:
            refresh_time = DEFAULT_REFRESH

        while self.output.window():
            self.output.run_command('refresh_tm1_ops_console')
            time.sleep(float(refresh_time))


class KillTm1ThreadCommand(sublime_plugin.WindowCommand):
    def run(self):
        self.window.show_input_panel('Thread ID:', '', self.killThread, None, None)

    def killThread(self, text):
        session = get_session(sublime.active_window())
        session.tm1.monitoring.cancel_thread(text)
        self.window.run_command("display_tm1_ops_console")
