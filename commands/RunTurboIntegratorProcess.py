import os
import re

import sublime
import sublime_plugin

from pelle.Pelle import get_session


class RunTurboIntegratorProcess(sublime_plugin.TextCommand):

    def run(self, edit, process, confirm, **kwargs):
        if confirm != 'Yes':
            return

        # Run Process
        self.session.run_process(process, kwargs)

    def input(self, args):
        print('Input called with ' + str(args))
        if not args:
            self.process = None
            self.window = sublime.active_window()
            self.view = self.window.active_view()
            self.session = get_session(self.window)

        if 'process' not in args:
            return ProcessInputHandler()
        elif not self.process:
            self.process = self.session.tm1.processes.get(args['process'])

        required = [p for p in self.process.parameters if p['Name'] not in args]
        if required:
            return ParameterInputHandler(required[0])

        if 'confirm' not in args:
            return ConfirmInputHandler(args)

    def input_description(self):
        try:
            return self.process.name
        except:
            return 'Execute Process'


class ProcessInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self):
        self.window = sublime.active_window()
        self.view = self.window.active_view()
        self.session = get_session(self.window)

        self.process = None
        # Get processes, reorder with callers on top
        processes = self.session.tm1.processes.get_all_names()
        callers = [p for p in processes if re.search(r'(\.?)(Call(er)?)(\.?)', p, re.IGNORECASE)]
        not_callers = [p for p in processes if p not in callers]
        self.processes = callers + not_callers

    def description(self, text, args):
        return str(args)
        # return text

    def list_items(self):
        return self.processes

    def initial_text(self):
        try:
            file = os.path.basename(self.view.file_name())
            file, ext = os.path.splitext(file)
            if ext == '.pro':
                return file
            return None
        except:
            return None


class ParameterInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, parameter):
        self.parameter = parameter

    def name(self):
        return self.parameter['Name']

    def placeholder(self):
        return self.parameter['Name']

    def description(self, text):
        return self.parameter['Name']

    def initial_text(self):
        return self.parameter['Value']

    def preview(self, text):
        if self.parameter['Prompt']:
            return '{} ({}): {}'.format(self.parameter['Prompt'], self.parameter['Name'], text)
        else:
            return '{}: {}'.format(self.parameter['Name'], text)


class ConfirmInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self, args):
        self.args = args
        pass

    def list_items(self):
        return ['Yes', 'No']

    def initial_text(self):
        return 'Yes'

    def preview(self, text):
        confirm = '<b>{}</b><br>'.format(
            self.args['process'])

        if self.args:
            confirm += '<ul>'
            for k, v in self.args.items():
                if k == 'process':
                    continue
                confirm += '<li>{} : <b>{}</b></li>'.format(k, v)
            confirm += '</ul>'

        confirm += 'Confirm Process Execute (Yes or No)'

        return sublime.Html(confirm)
