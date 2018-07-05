
import json
import os
import sublime
import sublime_plugin

from .connect import get_tm1_service

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


class GetObjectsFromServerCommand(sublime_plugin.WindowCommand):

    def run(self):
        active_project = sublime.active_window().project_data()
        project_settings = active_project['settings']
        session_settings = project_settings['TM1ConnectionSettings']

        completions = []

        self._session = get_tm1_service(session_settings)

        self._folder = sublime.active_window().extract_variables()['folder']
        processes = self._session.processes.get_all()
        for process in processes:
            try:
                self.output_process(process)
                completions.append(self.create_completion(process))
            except Exception as e:
                print('Error extracting process {}, {}'.format(process.name, e))
                pass

        cubes = self._session.cubes.get_all()
        for cube in [x for x in cubes if x.has_rules]:
            try:
                self.output_rule(cube)
            except Exception as e:
                print('Error extracting rule {}, {}'.format(cube.name, e))
                print(e)
                pass

        active_project['completions'] = completions
        sublime.active_window().set_project_data(active_project)

        return

    def create_completion(self, process):
        clean = [(' ', '_'), ('.', '-'), ('}', '')]
        name_clean = process.name.upper()

        for k, v in clean:
            name_clean = name_clean.replace(k, v)

        if len(process.parameters) == 0:
            comp = 'EXECUTEPROCESS(\'{}\');'.format(process.name)
        else:
            comp = 'EXECUTEPROCESS(\'{}\'\n'.format(process.name)
            for x in range(1, len(process.parameters) + 1):
                parameter = process.parameters[x - 1]
                if isinstance(parameter['Value'], str):
                    comp += '   , \'%s\', ${%s:\'%s\'}\n' % (
                        parameter['Name'], str(x), parameter['Value'])
                else:
                    comp += '   , \'%s\', ${%s:%s}\n' % (
                        parameter['Name'], str(x), parameter['Value'])
            comp += ');'

        return ["_TI-{}".format(name_clean), comp]

    def output_rule(self, cube):
        output_file = os.path.join(self._folder, cube.name + '.rux')

        header = ''
        header += '###############################################################################\n'
        header += '### Cube: {}\n'.format(cube.name)
        header += '### Dimensions:\n'

        for x in range(0, len(cube.dimensions)):
            header += '###     {}: {}\n'.format(x + 1, cube.dimensions[x])

        header += '###############################################################################\n\n'

        with open(output_file, 'w') as file:
            file.write(header)
            file.write(cube.rules.text.replace(header, ''))

    def output_process(self, process):
        output_file = os.path.join(self._folder, process.name + '.pro')

        procedure = {
            'prolog': process.prolog_procedure,
            'metadata': process.metadata_procedure,
            'data': process.data_procedure,
            'epilog': process.epilog_procedure
        }

        clean = {
            'beg1': '#****Begin: Generated Statements***',
            'end1': '#****End: Generated Statements****',
            'beg2': '#****GENERATED STATEMENTS START****',
            'end2': '#****GENERATED STATEMENTS FINISH****'
        }

        formatted_procedure = {
            'prolog': '',
            'metadata': '',
            'data': '',
            'epilog': ''
        }
 
        for section in procedure:
            buffer_fine_name = os.path.join(self._folder, section + 'buffer_file.txt')
            with open(buffer_fine_name, "w") as buffer_file:
                buffer_file.write(procedure[section])
            with open(buffer_fine_name, "r") as buffer_file:
                    counter = 1
                    for line in buffer_file:
                        if not counter % 2 == 0:
                            formatted_procedure[section] += line
                        counter += 1

        for section in formatted_procedure:
            beg_end = formatted_procedure[section].find(clean['beg1']) + len(clean['beg1']) + 1
            if formatted_procedure[section].find(clean['beg1']) >= 0 and not beg_end == formatted_procedure[section].find(clean['end1']):
                removingstring = formatted_procedure[section]
                beg = int(formatted_procedure[section].find(clean['beg1']))
                end = int(formatted_procedure[section].find(clean['end1']) + len(clean['end1']))
                removingstring = removingstring[beg:end]
                formatted_procedure[section] = formatted_procedure[section].replace(removingstring, '')

            beg_end = formatted_procedure[section].find(clean['beg2']) + len(clean['beg2']) + 1
            if formatted_procedure[section].find(clean['beg2']) >= 0 and not beg_end == formatted_procedure[section].find(clean['end2']):
                removingstring = formatted_procedure[section]
                removingstring = removingstring[int(formatted_procedure[section].find(clean['beg2'])):int(formatted_procedure[section].find(clean['end2']) + len(clean['end2']))]
                formatted_procedure[section] = formatted_procedure[section].replace(removingstring, '')

            for item in clean:
                formatted_procedure[section] = formatted_procedure[section].replace(clean[item], '')
                formatted_procedure[section] = formatted_procedure[
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
                    json.dumps(parameter['Value']))
                parameters += '###      prompt: {}\n'.format(
                    json.dumps(parameter['Prompt']))

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
                    getattr(process, '_datasource_{}'.format(item), ''))
                datasource += '###      {}: {}\n'.format(item, attribute)
        else:
            for item in [x for x in dir(process) if x.startswith('_datasource_')]:
                attribute = getattr(process, item, '')
                if attribute != '':
                    attribute = json.dumps(attribute)
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

        # write file
        with open(output_file, "w") as file:
            file.write(template.format(name=process.name, parameters=parameters, variables=variables,
                                       datasource=datasource, prolog=formatted_procedure['prolog'], metadata=formatted_procedure['metadata'],
                                       data=formatted_procedure['data'], epilog=formatted_procedure['epilog']))

        return
