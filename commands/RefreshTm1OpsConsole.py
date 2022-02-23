import sublime
import sublime_plugin
from prettytable import PrettyTable

from pelle.Session import get_session


class RefreshTm1OpsConsoleCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        session = get_session(sublime.active_window())

        threads = session.tm1.monitoring.get_threads()

        columns = ['ID', 'Type', 'Name', 'State', 'Function',
                   'ObjectName', 'RLocks', 'IXLocks', 'WLocks', 'ElapsedTime', 'WaitTime', 'Info']
        t = PrettyTable(columns)

        for row in threads:
            data_row = []
            user = row['Name'].split(' ')
            if user[-1].startswith('CAMID') and len(user) > 1:
                row['Name'] = ' '.join(user[:-1])
            if row['Function'] != 'GET /api/v1/Threads':
                for c in columns:
                    data_row.append(row[c])

                t.add_row(data_row)

        table = t.get_string()

        self.view.set_read_only(False)
        self.view.erase(edit, sublime.Region(0, self.view.size()))
        self.view.insert(edit, 0, table)
        self.view.set_read_only(True)
