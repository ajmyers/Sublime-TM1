
import json
import os
import re
import sublime
import sublime_plugin
import tempfile
import threading
import time
import traceback

from collections import OrderedDict
from datetime import datetime

from .connect import get_tm1_service
from TM1py.Exceptions import TM1pyException
from TM1py.Services import ServerService

from .include.prettytable.prettytable import PrettyTable

class runTurboIntegratorProcessCommand(sublime_plugin.WindowCommand):

    def run(self):
        self.active_project = sublime.active_window().project_data()
        self.project_settings = self.active_project['settings']
        self.session_settings = self.project_settings['TM1ConnectionSettings']

        self.session = get_tm1_service(self.session_settings)

        file = os.path.basename(self.window.active_view().file_name()).lower()
        file_base, file_extension = os.path.splitext(file)

        # Ensure file is correct extension
        processes = self.session.processes.get_all_names()
        if file_base not in processes:
            sublime.status_message('Error: {} is not a turbo integrator process'.format(file_base))

        self.process = self.session.processes.get(file_base)

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
            t = threading.Thread(target=self.run_process, args=())
            thread_name = 'TM1.TI.RUN.' + self.process.name.upper()
            t.daemon = True
            t.name = thread_name
            t.start()

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
            t = threading.Thread(target=self.run_process, args=())
            thread_name = 'TM1.TI.RUN.' + self.process.name.upper()
            t.daemon = True
            t.name = thread_name
            t.start()

    def run_process(self):
        # Get activeSession
        try:
            session_id = json.loads(self.session._tm1_rest.GET('/api/v1/ActiveSession').text).get('ID')
            service = ServerService(self.session._tm1_rest)
            service.initialize_message_log_delta_requests(filter='SessionID eq \'{}\''.format(session_id))
        except Exception:
            traceback.print_exc()


        # Create Output Window
        output = self.window.create_output_panel(self.process.name)
        output.run_command('erase_view')

        self.window.run_command("show_panel", {"panel": "output." + self.process.name})

        # Build parameters object
        run_param = OrderedDict()
        for par in self.process.parameters:
            if isinstance(par['OriginalValue'], int) or isinstance(par['OriginalValue'], float):
                par['SelectedValue'] = float(par['SelectedValue'])
            run_param[par['Name']] = par['SelectedValue']

        # Setup output text
        self.run_time = time.localtime()

        self.temp_dir = self.get_temp_dir_ti()

        ot = []

        ot.append('---------------------------------------------------')
        ot.append('Process: ' + self.process.name)
        ot.append('Run Time: ' + time.strftime('%a, %d %b %Y %H:%M:%S', self.run_time))

        if(len(self.process.parameters) > 0):
            ot.append('')
            ot.append('Run Parameters:')
            for name, val in run_param.items():
                ot.append('   {} : {}'.format(name, str(val)))

        ot.append("---------------------------------------------------")

        output.run_command('append', {'characters': '\n'.join(ot)})

        try:
            success, status, _ = self.session.processes.execute_with_return(self.process.name, **run_param)

            if success:
                ot.append('\n\nProcess completed successfully')
            else:
                ot.append('\n\nProcess failed with status: ' + status)

            with open(os.path.join(self.temp_dir, '_run.txt'), 'w') as f:
                f.write('\n'.join(ot) + '\n')

            output.run_command('append', {'characters': ot[-1]})
        except Exception:
            pass

        time.sleep(1)
        messages = service.execute_message_log_delta_request()

        self.process_logs_at_completion(messages, ot)

    def process_logs_at_completion(self, messages, run):
        # Find ThreadID of this execution
        thread_id = None
        for message in reversed(messages):
            if 'Process "{}"'.format(self.process.name) in message['Message']:
                thread_id = message['ThreadID']

        if not thread_id:
            raise Exception('Unable to find thread_id')

        messages = [m for m in messages if m['ThreadID'] == thread_id]

        columns = ['TimeStamp', 'Level', 'Logger', 'Message']

        table = PrettyTable(border=False)
        table.field_names = columns
        table.align = 'l'
        table.max_width = 1000
        for message in messages:
            table.add_row([str(message[col]) for col in columns])

        with open(os.path.join(self.temp_dir, '_tm1server.log'), 'w', newline='') as f:
            f.write(table.get_string())

        for message in messages:
            match = re.search(r'(TM1ProcessError)(.*)(.log)', message['Message'])
            if match:
                error_file = match.group(0)
                try:
                    content = self.session.processes.get_error_log_file_content(error_file)
                    with open(os.path.join(self.temp_dir, error_file), 'w', encoding='utf-8') as f:
                        f.write(content)
                except Exception:
                    traceback.print_exc()

    def get_temp_dir_ti(self):
        path = get_temp_dir()

        time_string = time.strftime('%y%m%d%H%M%S', self.run_time)
        folder = os.path.join(path, time_string + '_' + self.process.name)

        os.mkdir(folder)

        return folder

class clearTurboIntegratorLogs(sublime_plugin.WindowCommand):

    def run(self):
        folder_name = 'Turbo Integrator Logs'
        active_project = sublime.active_window().project_data()
        folders = active_project.get('folders', [])
        folders = [f for f in folders if os.path.exists(f['path']) and f['name'] != folder_name]
        active_project['folders'] = folders
        sublime.active_window().set_project_data(active_project)


def get_temp_dir():
    folder_name = 'Turbo Integrator Logs'
    # Cleanup
    active_project = sublime.active_window().project_data()
    folders = active_project.get('folders', [])
    folders = [f for f in folders if os.path.exists(f['path'])]
    log_folder = [f for f in folders if f['name'] == folder_name]
    if not log_folder:
        path = tempfile.mkdtemp(prefix='sublime-tm1-ti-logs-')
        folders.append({'name': folder_name, 'path': path})
        active_project['folders'] = folders
        sublime.active_window().set_project_data(active_project)
    else:
        path = log_folder[0].get('path')

    return path
