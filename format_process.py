
import json
import os
import re
import sublime
import sublime_plugin
import yaml

from .format import format_procedure

from TM1py import Process

PROCESS_TEMPLATE = '''###############################################################################
### Process: {name}
###############################################################################

###############################################################################
### PARAMETERS:
{parameters}###############################################################################

###############################################################################
### DATASOURCE:
{datasource}###############################################################################

###############################################################################
### VARIABLES:
{variables}###############################################################################

###############################################################################
### PROLOG: ###################################################################

{prolog}

###############################################################################
### METADATA: #################################################################

{metadata}

###############################################################################
### DATA: #####################################################################

{data}

###############################################################################
### EPILOG: ###################################################################

{epilog}
'''


def set_config(value):
    active_project = sublime.active_window().project_data()
    project_settings = active_project.get('settings', {})

    if not active_project:
        sublime.message_dialog("Active window is not currently configured as a project.\n\nPlease go to Project -> Save Project As to continue")
        return

    project_settings['format_process_on_update'] = value

    sublime.active_window().set_project_data(active_project)


class enableFormatProcessOnSave(sublime_plugin.WindowCommand):
    def run(self):
        set_config(True)


class disableFormatProcessOnSave(sublime_plugin.WindowCommand):
    def run(self):
        set_config(False)


class onSaveListener(sublime_plugin.EventListener):
    def on_pre_save(self, view):
        active_project = sublime.active_window().project_data()
        project_settings = active_project.get('settings', {})

        if not view.file_name().endswith(".pro"):
            return

        if project_settings.get('format_process_on_update', False) == False:
            return

        try:
            view.run_command('format_turbo_integrator_process')
        except Exception as e:
            print(e)


class formatTurboIntegratorProcess(sublime_plugin.WindowCommand):
    def run(self):

        if not self.view.file_name().endswith(".pro"):
            return

        self.view.run_command('format_turbo_integrator_process')


class formatTurboIntegratorProcessCommand(sublime_plugin.TextCommand):
    def run(self, edit):

        process = view_to_process(self.view, None)

        process.prolog_procedure = format_procedure(process.prolog_procedure)
        process.metadata_procedure = format_procedure(process.metadata_procedure)
        process.data_procedure = format_procedure(process.data_procedure)
        process.epilog_procedure = format_procedure(process.epilog_procedure)

        text = process_to_view(process)

        text = text.replace('\r\n', '\n')

        selections = [sel for sel in self.view.sel()]

        region = self.view.split_by_newlines(sublime.Region(0, self.view.size()))

        self.view.erase(edit, sublime.Region(0, self.view.size()))
        self.view.insert(edit, 0, text)

        self.view.sel().clear()

        for sel in selections:
            self.view.sel().add(sel)


def view_to_process(view, process=None):

    if not process:
        active_file = os.path.basename(view.file_name())
        active_file_base, active_file_ext = os.path.splitext(active_file)

        process = Process(name=active_file_base)

    regions = view.split_by_newlines(sublime.Region(0, view.size()))
    text = [view.substr(region).rstrip() + '\r\n' for region in regions]

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
                section_text[parse_section] += line.rstrip() + '\r\n'
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

            var_name = var_name.strip()
            process.add_variable(var_name, var_type)

    process.prolog_procedure = section_text['PROLOG'].strip()
    process.metadata_procedure = section_text['METADATA'].strip()
    process.data_procedure = section_text['DATA'].strip()
    process.epilog_procedure = section_text['EPILOG'].strip()

    return process


def process_to_view(process):

    procedure = {
        'prolog': process.prolog_procedure,
        'metadata': process.metadata_procedure,
        'data': process.data_procedure,
        'epilog': process.epilog_procedure
    }

    clean = [
        '#****Begin: Generated Statements***',
        '#****End: Generated Statements****',
        '#****GENERATED STATEMENTS START****',
        '#****GENERATED STATEMENTS FINISH****'
    ]

    for section in procedure:
        for item in clean:
            procedure[section] = procedure[section].replace(item, '')
            procedure[section] = procedure[
                section].lstrip("\r\n").rstrip("\r\n")

    template = PROCESS_TEMPLATE

    # format parameters
    parameters = ''
    if len(process.parameters) == 0:
        parameters += '###      None\n'
    else:
        for parameter in process.parameters:
            parameters += '###    - name: {}\n'.format(parameter['Name'])
            parameters += '###      value: {}\n'.format(
                json.dumps(parameter['Value'], ensure_ascii=False))
            parameters += '###      prompt: {}\n'.format(
                json.dumps(parameter['Prompt'], ensure_ascii=False))

    # format datasource
    datasource_keys = {
        'ASCII': [
            'type',
            'data_source_name_for_client',
            'data_source_name_for_server',
            'ascii_decimal_separator',
            'ascii_delimiter_char',
            'ascii_delimiter_type',
            'ascii_header_records',
            'ascii_quote_character',
            'ascii_thousand_separator'
        ],
        'TM1CubeView': [
            'type',
            'data_source_name_for_client',
            'data_source_name_for_server',
            'view'
        ],
        'ODBC': [
            'type',
            'data_source_name_for_client',
            'data_source_name_for_server',
            'user_name',
            'password',
            'query',
            'uses_unicode'
        ],
        'TM1DimensionSubset': [
            'type',
            'data_source_name_for_client',
            'data_source_name_for_server',
            'subset'
        ]
    }

    datasource = ''
    if process.datasource_type == 'None':
        datasource += '###      None\n'
    elif process.datasource_type in datasource_keys:
        for item in datasource_keys[process.datasource_type]:
            attribute = json.dumps(
                getattr(process, '_datasource_{}'.format(item), ''), ensure_ascii=False)
            datasource += '###      {}: {}\n'.format(item, attribute)
    else:
        for item in [x for x in dir(process) if x.startswith('_datasource_')]:
            attribute = getattr(process, item, '')
            if attribute != '':
                attribute = json.dumps(attribute, ensure_ascii=False)
                datasource += '###      {}: {}\n'.format(
                    item[12:], attribute)

    # format variables
    variables = ''
    if len(process.variables) == 0:
        variables += '###      None\n'
    else:
        for variable in process.variables:
            variables += '###    - name: {} ({})\n'.format(
                variable['Name'], variable['Type'])

    view = template.format(name=process.name, parameters=parameters, variables=variables,
                           datasource=datasource, prolog=procedure['prolog'], metadata=procedure['metadata'],
                           data=procedure['data'], epilog=procedure['epilog'])

    return view.replace('\r\n', '\n')
