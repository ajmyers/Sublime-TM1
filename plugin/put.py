"""TM1: Put - Push Object to Server: a process or a cube's rules, from the file in the active view."""

import os

import sublime
import sublime_plugin

from ..core import process_file, rule_file
from . import diagnostics, gateway


def put_process(name, text):
    def work(client):
        from skipcheck_tm1.errors import Tm1NotFoundError

        process = process_file.text_to_process(text, name)
        try:
            client.processes.get(name, select='Name')
        except Tm1NotFoundError:
            client.processes.create(process)
        else:
            client.processes.update(name, process)
        return [(process_file.error_line(text, error.procedure.value, error.line_number), error.message)
                for error in client.processes.compile(name)]
    return work


def put_rules(name, text):
    def work(client):
        from skipcheck_tm1.model import Cube

        client.cubes.update(name, Cube(rules=rule_file.text_to_rules(text)))
        return [(rule_file.error_line(text, error.line_number), error.message)
                for error in client.cubes.check_rules(name)]
    return work


class PutObjectToServer(sublime_plugin.WindowCommand):
    def is_enabled(self):
        view = self.window.active_view()
        return bool(view and (view.file_name() or '').endswith(('.pro', '.rux')))

    def run(self):
        view = self.window.active_view()
        if view is None or not (view.file_name() or '').endswith(('.pro', '.rux')):
            sublime.error_message('TM1: Put works on a process (.pro) or rules (.rux) file.')
            return
        tm1 = gateway.for_window(self.window)
        if tm1 is None:
            return
        if view.is_dirty():
            view.run_command('save')
        diagnostics.clear(view)
        name, kind = os.path.splitext(os.path.basename(view.file_name()))
        text = view.substr(sublime.Region(0, view.size()))
        what = 'process' if kind == '.pro' else 'rules of'
        self.window.status_message('TM1: putting {} {}...'.format(what, name))
        work = put_process(name, text) if kind == '.pro' else put_rules(name, text)

        def done(errors):
            if errors:
                diagnostics.show(view, [(line or 0, message) for line, message in errors])
                self.window.status_message('TM1: {} {} put, with {} error{}'.format(
                    what, name, len(errors), '' if len(errors) == 1 else 's'))
            else:
                self.window.status_message('TM1: {} {} put, no errors'.format(what, name))

        tm1.run(self.window, work, done)
