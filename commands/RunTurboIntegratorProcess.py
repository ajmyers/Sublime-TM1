
import os
import sublime
import sublime_plugin
from collections import OrderedDict
from ..utils.Session import get_session


class runTurboIntegratorProcess(sublime_plugin.WindowCommand):

    def run(self):
        window = sublime.active_window()
        view = window.active_view()
        self.session = get_session(window)

        file = os.path.basename(view.file_name())
        file, ext = os.path.splitext(file)

        processes = self.session.tm1.processes.get_all_names()
        if file not in processes:
            sublime.status_message('Error: {} is not a turbo integrator process'.format(file))

        self.process = self.session.tm1.processes.get(file)

        # Fix this
        for parameter in self.process.parameters:
            parameter['OriginalValue'] = parameter['Value']
            if not isinstance(parameter['Value'], str):
                parameter['Value'] = str(parameter['Value'])

        self.get_parameter_input()

    def get_parameter_input(self):
        prompt = ''
        for par in self.process.parameters:
            if 'SelectedValue' not in par:
                prompt_type = 'String'
                if not isinstance(par['OriginalValue'], str):
                    prompt_type = 'Number'
                if len(par['Prompt']) > 0:
                    prompt = par['Prompt'] + ' -- '
                prompt += par['Name'] + ' (' + prompt_type + ')'
                self.window.show_input_panel(prompt, par['Value'], self.parameter_input_done, None, None)
                break
        else:
            self.run_process()

    def parameter_input_done(self, text):
        parameter_defined = False
        for par in self.process.parameters:
            if 'SelectedValue' not in par and not parameter_defined:
                par['SelectedValue'] = text
                parameter_defined = True
            elif 'SelectedValue' not in par and parameter_defined:
                self.get_parameter_input()
                break

        parameter_all_set = True
        for par in self.process.parameters:
            if 'SelectedValue' not in par:
                parameter_all_set = False

        if parameter_all_set:
            self.run_process()

    def run_process(self):
        name = self.process.name
        parameters = OrderedDict()
        for par in self.process.parameters:
            if isinstance(par['OriginalValue'], int) or isinstance(par['OriginalValue'], float):
                par['SelectedValue'] = float(par['SelectedValue'])
            parameters[par['Name']] = par['SelectedValue']

        self.session.run_process(name, parameters)






