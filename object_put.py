import connect
import os
import re
import sublime
import sublime_plugin
import threading
import yaml

from TM1py import Process
from TM1py.Exceptions import TM1pyException


class PutObjectToServerCommand(sublime_plugin.WindowCommand):

    def run(self):
        active_project = sublime.active_window().project_data()
        project_settings = active_project['settings']
        session_settings = project_settings['TM1ConnectionSettings']

        self._session = connect.get_tm1_service(session_settings)

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
            cube = self._session.cubes.get(self.active_file_base)

            cube.rules = rules
            self._session.cubes.update(cube)

            sublime.message_dialog('Updated {} Rule Successfully'.format(self.active_file_base))
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

        regions = active_view.split_by_newlines(sublime.Region(0, active_view.size()))
        text = [active_view.substr(region).rstrip() + '\n' for region in regions]

        # Parse Sections
        sections = ['PARAMETERS', 'DATASOURCE', 'VARIABLES', 'PROLOG', 'METADATA', 'DATA', 'EPILOG']
        section_text = {}

        comment_line = '###############################################################################'
        for section in sections:
            parse_section = section
            section_text[parse_section] = ''

            regex_find = re.compile('^(#+\s*?)?(' + parse_section + ')(:|;)')
            regex_end = re.compile('^(#+\s*?)?({})(:|;)'.format('|'.join(sections)))

            search_active = False

            for line in text:
                if search_active and not regex_end.search(line) and line.rstrip() != comment_line:
                    section_text[parse_section] += line.rstrip() + '\n'
                if regex_end.search(line) and search_active:
                    break
                if regex_find.search(line) and not search_active:
                    search_active = True

        for section in ['PARAMETERS', 'DATASOURCE', 'VARIABLES']:
            section_text[section] = section_text[section].replace("### ", "")

        parameters = yaml.load(section_text['PARAMETERS'])
        if parameters == 'None':
            parameters = []

        for parameter in process.parameters.copy():
            process.remove_parameter(parameter['Name'])

        for parameter in parameters:
            process.add_parameter(parameter['name'], parameter['prompt'], parameter['value'])

        # Datasource
        datasource = yaml.load(section_text['DATASOURCE'])

        if datasource == 'None':
            datasource = {'type': 'None'}

        for key, item in datasource.items():
            obj_key = 'datasource_' + key
            try:
                if obj_key in dir(process):
                    setattr(process, '' + obj_key, item)
                else:
                    print('encountered unknown datasource setting: ' + key)
            except Exception as e:
                sublime.message_dialog('An error occurred updating {}\n\n{}'.format(process_name, e))
                raise

        # Variables
        variables = yaml.load(section_text['VARIABLES'])
        for variable in process.variables.copy():
            process.remove_variable(variable['Name'])

        if variables != 'None':
            for x in variables:
                if '(Numeric)' in x['name']:
                    var_type = 'Numeric'
                    var_name = x['name'].replace('(Numeric)', '')
                else:
                    var_type = 'String'
                    var_name = x['name'].replace('(String)', '')

                var_name = var_name.rstrip().lstrip()
                process.add_variable(var_name, var_type)

        process.prolog_procedure = section_text['PROLOG']
        process.metadata_procedure = section_text['METADATA']
        process.data_procedure = section_text['DATA']
        process.epilog_procedure = section_text['EPILOG']

        try:
            if not update_process:
                self._session.processes.create(process)
                sublime.message_dialog('Created {} TI Process Successfully'.format(process_name))
            else:
                self._session.processes.update(process)
                sublime.message_dialog('Updated {} TI Process Successfully'.format(process_name))
        except Exception as e:
            sublime.message_dialog('An error occurred updating {}\n\n{}'.format(process_name, e))
            raise
