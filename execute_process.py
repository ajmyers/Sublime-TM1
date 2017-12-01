
import json
import os
import sublime
import sublime_plugin
import threading
import time

from .connect import get_tm1_service
from TM1py.Exceptions import TM1pyException


class runTurboIntegratorProcessCommand(sublime_plugin.WindowCommand):

    def run(self):
        active_project = sublime.active_window().project_data()
        project_settings = active_project['settings']
        session_settings = project_settings['TM1ConnectionSettings']

        self._session = get_tm1_service(session_settings)

        file = os.path.basename(self.window.active_view().file_name()).lower()
        file_base, file_extension = os.path.splitext(file)

        # Ensure file is correct extension
        processes = self._session.processes.get_all_names()
        if file_base not in processes:
            sublime.status_message('Error: {} is not a turbo integrator process'.format(file_base))

        self._process = self._session.processes.get(file_base)

        # Fix this
        for parameter in self._process.parameters:
            parameter['OriginalValue'] = parameter['Value']
            if not isinstance(parameter['Value'], str):
                parameter['Value'] = str(parameter['Value'])

        self.get_parameter_input()

    def get_parameter_input(self):
        prompt = ''
        for par in self._process.parameters:
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
            t = threading.Thread(target=self.run_process, args=())
            thread_name = 'TM1.TI.RUN.' + self._process.name.upper()
            t.daemon = True
            t.name = thread_name
            t.start()

    def parameter_input_done(self, text):
        parameter_defined = False
        for par in self._process.parameters:
            if 'SelectedValue' not in par and not parameter_defined:
                par['SelectedValue'] = text
                parameter_defined = True
            elif 'SelectedValue' not in par and parameter_defined:
                self.get_parameter_input()
                break

        parameter_all_set = True
        for par in self._process.parameters:
            if 'SelectedValue' not in par:
                parameter_all_set = False

        if parameter_all_set:
            t = threading.Thread(target=self.run_process, args=())
            thread_name = 'TM1.TI.RUN.' + self._process.name.upper()
            t.daemon = True
            t.name = thread_name
            t.start()

    def run_process(self):
        # Create Output Window
        output = self.window.create_output_panel(self._process.name)
        output.run_command('erase_view')

        self.window.run_command("show_panel", {"panel": "output." + self._process.name})

        # Build parameters object
        run_param = []
        for par in self._process.parameters:
            if isinstance(par['OriginalValue'], int) or isinstance(par['OriginalValue'], float):
                par['SelectedValue'] = float(par['SelectedValue'])
            run_param.append({'Name': par['Name'], 'Value': par['SelectedValue']})

        # Setup output text
        self.output_text = []
        self.run_time = time.localtime()

        ot = self.output_text

        ot.append('---------------------------------------------------')
        ot.append('Process: ' + self._process.name)
        ot.append('Run Time: ' + time.strftime('%a, %d %b %Y %H:%M:%S', self.run_time))

        if(len(self._process.parameters) > 0):
            ot.append('')
            ot.append('Run Parameters:')
            for par in run_param:
                ot.append('   {} : {}'.format(par['Name'], str(par['Value'])))

        ot.append("---------------------------------------------------")

        output.run_command('append', {'characters': '\n'.join(ot)})
        ot = ['']

        try:
            response = self._session.processes.execute(self._process.name, {'Parameters': run_param})

            ot.append('Process completed successfully with no errors')
            ot.append(response)
        except TM1pyException as e:
            result = json.loads(e._response)['error']
            ot.append('Process completed with errors:')
            ot.append('   Error: {}'.format(result['message']))
            ot.append('   Message: {}'.format(result['innererror']['ProcessError'].rstrip()))
