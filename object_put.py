
import os
import re
import sublime
import sublime_plugin
import threading
import yaml

from .connect import get_tm1_service
from .format_process import view_to_process

from TM1py import Process
from TM1py.Exceptions import TM1pyException


class PutObjectToServerCommand(sublime_plugin.WindowCommand):

    def run(self):
        active_project = sublime.active_window().project_data()
        project_settings = active_project['settings']
        session_settings = project_settings['TM1ConnectionSettings']

        self._session = get_tm1_service(session_settings)

        # Determine if rule or process
        self.active_file = os.path.basename(self.window.active_view().file_name())
        self.active_file_base, self.active_file_ext = os.path.splitext(self.active_file)

        funcmap = [
            (['.rux', '.rule'], self.put_rule),
            (['.pro', '.ti'], self.put_turbointegrator)
        ]

        for ext_list, put_func in funcmap:
            if(self.active_file_ext.lower() in ext_list):
                self.window.active_view().run_command("save")
                thread_name = 'TM1.UPDATE.{}'.format(self.active_file_base)
                if len([x for x in threading.enumerate() if x.getName() == thread_name]) == 0:
                    t = threading.Thread(name=thread_name, daemon=True, target=put_func, args=(self.window.active_view(),))
                    t.start()
                else:
                    sublime.status_message("A previous save of " + self.active_file_base + " is already in progress")

    def put_rule(self, active_view):
        sublime.status_message("Processing server update of rule: " + self.active_file_base)

        regions = active_view.split_by_newlines(sublime.Region(0, active_view.size()))
        rules = ''.join([active_view.substr(region).rstrip() + '\n' for region in regions])

        try:
            cube_name = self.active_file_base
            cube = self._session.cubes.get(cube_name)

            cube.rules = rules
            self._session.cubes.update(cube)

            request = "/api/v1/Cubes('{}')/tm1.CheckRules".format(cube_name)
            errors = self._session._tm1_rest.POST(request, '').json()['value']
            if errors:
                sublime.message_dialog('Error compiling {}:\n\nLine {}\n\n{}'.format(cube_name, str(errors[0]['LineNumber']), errors[0]['Message']))
            else:
                sublime.message_dialog('Updated {} Rule Successfully'.format(cube_name))
        except Exception as e:
            sublime.message_dialog('An error occurred updating {}\n\n{}'.format(self.active_file_base, e))

    def put_turbointegrator(self, active_view):
        process_name = self.active_file_base

        sublime.status_message('Processing server update of ti process: {}'.format(process_name))

        try:
            process = self._session.processes.get(process_name)
            update_process = True
        except TM1pyException as e:
            process = Process(name=process_name)
            update_process = False

        process = view_to_process(active_view, process)

        try:
            if not update_process:
                self._session.processes.create(process)
            else:
                self._session.processes.update(process)

            errors = self._session.processes.compile(process_name)
            if errors:
                sublime.message_dialog('Error compiling {}: \n\nProcedure: {} (~Line {})\n\n{}'.format(process_name, errors[0]['Procedure'], str(errors[0]['LineNumber']), errors[0]['Message']))
            else:
                sublime.message_dialog('Updated {} TI Process Successfully'.format(process_name))
        except Exception as e:
            sublime.message_dialog('An error occurred updating {}\n\n{}'.format(process_name, e))
            raise
