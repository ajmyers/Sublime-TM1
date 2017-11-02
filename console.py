import connect
import sublime
import sublime_plugin
import threading
import time

from prettytable import PrettyTable


class displayTm1OpsConsoleCommand(sublime_plugin.WindowCommand):

    def run(self):
        active_project = sublime.active_window().project_data()
        project_settings = active_project['settings']
        self._session = project_settings['TM1ConnectionSettings']

        # Get instance name
        window_name = 'Console'

        # Create Output Window
        self._output = self.window.create_output_panel(window_name)
        self._output.run_command('erase_view')
        self.window.run_command('show_panel', {'panel': 'output.{}'.format(window_name)})

        self._output.set_read_only(True)

        t = threading.Thread(target=self.run_refresh, daemon=True)
        t.start()

    def run_refresh(self):
        while self._output.window():
            self._output.run_command('refresh_tm1_ops_console', {'session_settings': self._session})
            time.sleep(2.5)


class killTm1ThreadCommand(sublime_plugin.WindowCommand):

    def run(self):
        self.window.show_input_panel('Thread ID:', '', self.killThread, None, None)

    def killThread(self, text):
        active_project = sublime.active_window().project_data()
        project_settings = active_project['settings']
        session_settings = project_settings['TM1ConnectionSettings']

        self._session = connect.get_tm1_service(session_settings)

        self._session.monitoring.cancel_thread(text)
        self.window.run_command("display_tm1_ops_console")


class refreshTm1OpsConsoleCommand(sublime_plugin.TextCommand):
    def run(self, edit, session_settings):
        session = connect.get_tm1_service(session_settings)

        threads = session.monitoring.get_threads()

        columns = ['ID', 'Type', 'Name', 'State', 'Function',
                   'ObjectName', 'RLocks', 'IXLocks', 'WLocks', 'ElapsedTime', 'WaitTime', 'Info']
        t = PrettyTable(columns)

        for row in threads:
            data_row = []
            for c in columns:
                data_row.append(row[c])

            t.add_row(data_row)

        table = t.get_string()

        self.view.set_read_only(False)
        self.view.erase(edit, sublime.Region(0, self.view.size()))
        self.view.insert(edit, 0, table)
        self.view.set_read_only(True)
