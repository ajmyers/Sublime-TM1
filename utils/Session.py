import glob
import json
import os
import re
import tempfile
import time
import traceback

import sublime
from TM1py import TM1Service, Process, Cube, ServerService
from TM1py.Exceptions import TM1pyException

from . import Utils
from ..prettytable.prettytable import PrettyTable

SESSIONS = {}

TI_LOG_FOLDER = 'Turbo Integrator Logs'


def get_session(window):
    if not window.project_file_name():
        sublime.message_dialog('There is no project opened in this current window')
        raise Exception()

    session_name = os.path.split(window.project_file_name())
    session_name = os.path.splitext(session_name[1])[0]

    session = SESSIONS.get(session_name)
    if not session:
        session = TM1Session(window, session_name)
        SESSIONS[session_name] = session

    return session


class TM1Session:
    def __init__(self, window, name):
        self.window = window
        self.name = name

        self.project_settings = window.project_data()
        self.plugin_settings = self.project_settings.get('settings', {})
        self.connection_settings = self.plugin_settings.get('tm1_connection')

        # Legacy
        if not self.connection_settings:
            self.connection_settings = self.plugin_settings.get('TM1ConnectionSettings', None)
            self.connection_settings = Utils.cleanup_old_settings(self.connection_settings)

        if not self.connection_settings:
            sublime.message_dialog(
                'No TM1 connection settings. Please run TM1 Config Setup command from command palette')
            raise Exception()

        try:
            settings = self.connection_settings.copy()
            settings['password'] = Utils.decode(settings['password'])
            self.tm1 = TM1Service(**settings)
        except Exception as e:
            traceback.print_exc()
            sublime.message_dialog('Unable to establish TM1 session with message: \n\n' + str(e))
            raise

    def refresh_objects(self):
        main_folder = self.project_settings['folders'][0]['path']
        existing = glob.glob(os.path.join(main_folder, '*.pro')) + \
                   glob.glob(os.path.join(main_folder, '*.rux'))

        # Clear existing files from project folder
        for file in existing:
            try:
                os.remove(file)
            except Exception:
                traceback.print_exc()

        # Get objects from server
        cubes = self.tm1.cubes.get_all()
        processes = self.tm1.processes.get_all()

        # Write cube rules to files
        folder = os.path.join(main_folder, 'rules')
        if not os.path.exists(folder): os.mkdir(folder)
        for cube in [x for x in cubes if x.has_rules]:
            file = os.path.join(folder, cube.name + '.rux')
            content = Utils.cube_rule_to_text(cube)
            with open(file, 'w', encoding='utf-8') as f:
                f.write(content)

        # Write processes to files
        folder = os.path.join(main_folder, 'processes')
        if not os.path.exists(folder): os.mkdir(folder)
        for process in processes:
            file = os.path.join(folder, process.name + '.pro')
            content = Utils.process_to_text(process)
            with open(file, 'w', encoding='utf-8') as f:
                f.write(content)

        self.project_settings['completions'] = {}

        # Populate Rule completions
        completions = [Utils.generate_rule_completion(cube) for cube in cubes]
        self.project_settings['completions']['source.tm1.rule'] = completions

        # Populate TI completions
        completions = [Utils.generate_turbo_integrator_completion(process) for process in processes] + \
                      [Utils.generate_turbo_integrator_cube_completion(cube, 'CELLGETN') for cube in cubes] + \
                      [Utils.generate_turbo_integrator_cube_completion(cube, 'CELLPUTN') for cube in cubes] + \
                      [Utils.generate_turbo_integrator_cube_completion(cube, 'CELLINCREMENTN') for cube in cubes] + \
                      [Utils.generate_turbo_integrator_cube_completion(cube, 'CELLGETS') for cube in cubes] + \
                      [Utils.generate_turbo_integrator_cube_completion(cube, 'CELLPUTS') for cube in cubes] + \
                      [Utils.generate_turbo_integrator_cube_locals_completion(cube) for cube in cubes]

        self.project_settings['completions']['source.tm1.ti'] = completions

        self.window.set_project_data(self.project_settings)

    def update_object(self, view):
        file = os.path.basename(view.file_name())
        file, ext = os.path.splitext(file)

        view.run_command("save")
        view.erase_regions('error')

        if ext == '.rux':
            self._update_rule(view)
        elif ext == '.pro':
            self._update_process(view)
        else:
            sublime.message_dialog('This operation can only be performed for .rux and .pro files')
            return

    def _update_rule(self, view):
        file = os.path.basename(view.file_name())
        file, ext = os.path.splitext(file)

        sublime.status_message('Processing server update of rule: {}'.format(file))

        content = view.substr(sublime.Region(0, view.size()))
        content = content.replace('\r\n', '\n').strip('\n') + '\n'

        try:
            cube = self.tm1.cubes.get(file)
        except TM1pyException:
            cube = Cube(name=file)

        cube.rules = content

        def do_rule_update():
            self.tm1.cubes.update(cube)
            errors = self.tm1.cubes.check_rules(cube.name)
            if errors:
                Utils.highlight_errors(view, errors[0]['Message'], errors[0]['LineNumber'], None)
            else:
                sublime.message_dialog('Updated {} Rule Successfully'.format(cube.name))

        Utils.run_async(do_rule_update)

    def _update_process(self, view):
        file = os.path.basename(view.file_name())
        file, ext = os.path.splitext(file)

        sublime.status_message('Processing server update of TI process: {}'.format(file))

        try:
            process = self.tm1.processes.get(file)
        except TM1pyException:
            process = Process(name=file)

        process = Utils.view_to_process(view, process)

        def do_process_update():
            self.tm1.processes.update_or_create(process)
            errors = self.tm1.processes.compile(file)
            if errors:
                Utils.highlight_errors(view, errors[0]['Message'], errors[0]['LineNumber'], errors[0]['Procedure'])
            else:
                sublime.message_dialog('Updated {} TI Process Successfully'.format(file))

        Utils.run_async(do_process_update)

    def run_process(self, name, parameters):
        try:
            session_id = json.loads(self.tm1._tm1_rest.GET('/api/v1/ActiveSession').text).get('ID')
            server_service = ServerService(self.tm1._tm1_rest)
            server_service.initialize_message_log_delta_requests(filter='SessionID eq \'{}\''.format(session_id))
        except Exception:
            traceback.print_exc()

        # Create Output Window
        output = self.window.create_output_panel(name)
        output.run_command('erase_view')

        self.window.run_command("show_panel", {"panel": "output." + name})

        # Setup output text
        run_time = time.localtime()
        folder = self._get_output_directory(name, run_time)

        ot = []
        ot.append('---------------------------------------------------')
        ot.append('Process : ' + name)
        ot.append('Run Time: ' + time.strftime('%a, %d %b %Y %H:%M:%S', run_time))

        if parameters:
            ot.append('')
            ot.append('Run Parameters:')
            for param, val in parameters.items():
                ot.append('   {} : {}'.format(param, str(val)))

        ot.append("---------------------------------------------------")

        with open(os.path.join(folder, '_run.txt'), 'w') as f:
            f.write('\n'.join(ot))

        output.run_command('append', {'characters': '\n'.join(ot)})

        def do_run_process():
            try:
                success, status, _ = self.tm1.processes.execute_with_return(name, **parameters)
                message = 'Process completed with status: ' + status
                with open(os.path.join(folder, '_run.txt'), 'a') as f:
                    f.write('\n\n' + message)
                output.run_command('append', {'characters': '\n\n' + message})
            except Exception:
                traceback.print_exc()

            time.sleep(1)
            messages = server_service.execute_message_log_delta_request()

            # Find ThreadID of this execution
            thread_id = None
            for message in reversed(messages):
                if 'Process "{}"'.format(name) in message['Message']:
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

            with open(os.path.join(folder, '_tm1server.log'), 'w') as f:
                f.write(table.get_string())

            for message in messages:
                match = re.search(r'(TM1ProcessError)(.*)(.log)', message['Message'])
                if match:
                    error_file = match.group(0)
                    try:
                        content = self.tm1.processes.get_error_log_file_content(error_file)
                        with open(os.path.join(folder, error_file), 'w', encoding='utf-8') as f:
                            f.write(content)
                    except Exception:
                        traceback.print_exc()

        Utils.run_async(do_run_process)

    def clear_turbo_integrator_logs(self):
        folders = self.project_settings.get('folders', [])
        folders = [f for f in folders if os.path.exists(f['path']) and f.get('name', '') != TI_LOG_FOLDER]
        self.project_settings['folders'] = folders
        sublime.active_window().set_project_data(self.project_settings)

    def _get_output_directory(self, name, run_time):
        path = self._get_temp_dir(TI_LOG_FOLDER)
        time_string = time.strftime('%y%m%d%H%M%S', run_time)
        folder = os.path.join(path, time_string + '_' + name)
        os.mkdir(folder)
        return folder

    def _get_temp_dir(self, name):
        folders = self.project_settings['folders']
        folders = [f for f in folders if os.path.exists(f['path'])]
        folder = [f for f in folders if f.get('name', '') == name]
        if not folder:
            path = tempfile.mkdtemp(prefix='sublime-tm1-ti-logs-')
            folders.append({'name': name, 'path': path})
            self.project_settings['folders'] = folders
            sublime.active_window().set_project_data(self.project_settings)
        else:
            path = folder[0].get('path')

        return path
