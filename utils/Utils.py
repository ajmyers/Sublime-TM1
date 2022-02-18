import os
import re
import threading
import time
from base64 import urlsafe_b64decode

import sublime as sublime
import yaml
from TM1py import Process

from ..template import RuleTemplate, ProcessTemplate


def _decode(key, enc):
    dec = []
    enc = urlsafe_b64decode(enc).decode()
    for i in range(len(enc)):
        key_c = key[i % len(key)]
        dec_c = chr((256 + ord(enc[i]) - ord(key_c)) % 256)
        dec.append(dec_c)
    return "".join(dec)


def cleanup_settings(connection_settings):
    return {
        'address': connection_settings['ServerAddress'],
        'port': connection_settings['PortNumber'],
        'user': connection_settings['UserName'],
        'ssl': True if connection_settings['UseSSL'] == 'T' else False,
        'password': _decode("1234567890", connection_settings['Password']),
        'namespace': connection_settings['CAMNamespaceID'],
        'async_requests_mode': True if connection_settings.get('UseAsync', 'F') == 'T' else False
    }


def cube_rule_to_text(cube):
    dimensions = '\n'.join([RuleTemplate.DIMENSION_ROW.format(index=index, dimension=dimension) for index, dimension in
                            enumerate((dim for dim in cube.dimensions if dim != 'Sandboxes'), start=1)])
    header = RuleTemplate.HEADER.format(cube=cube.name, dimensions=dimensions)
    body = cube.rules.text.replace(header, '').strip('\n')
    content = RuleTemplate.TEMPLATE.format(header=header, body=body)

    return content


def process_to_text(process):
    procedure = {
        'prolog': process.prolog_procedure,
        'metadata': process.metadata_procedure,
        'data': process.data_procedure,
        'epilog': process.epilog_procedure
    }

    # Cleanup
    procedure = {k: ProcessTemplate.clean_procedure(v) for k, v in procedure.items()}

    # Set parameters, datasource, variables
    parameters = ProcessTemplate.generate_parameters(process.parameters)
    datasource = ProcessTemplate.generate_datasource(process)
    variables = ProcessTemplate.generate_variables(process.variables)

    content = ProcessTemplate.TEMPLATE.format(name=process.name, parameters=parameters, variables=variables,
                                              datasource=datasource, prolog=procedure['prolog'],
                                              metadata=procedure['metadata'],
                                              data=procedure['data'], epilog=procedure['epilog'])

    return content


def generate_turbo_integrator_completion(process):
    output = []
    if not process.parameters:
        output.append('EXECUTEPROCESS(\'{}\');'.format(process.name))
    else:
        output.append('EXECUTEPROCESS(\'{}\''.format(process.name))
        for index, parameter in enumerate(process.parameters, start=1):
            name = parameter['Name']
            value = parameter['Value']
            if isinstance(parameter['Value'], str):
                output.append('   , \'%s\', ${%s:\'%s\'}' % (name, str(index), value))
            else:
                output.append('   , \'%s\', ${%s:%s}' % (name, str(index), value))
        output.append(');')

    clean = [(' ', '_'), ('.', '-'), ('}', '')]
    name = process.name.upper()
    for k, v in clean:
        name = name.replace(k, v)

    return ["_TI-{}".format(name), '\n'.join(output)]


def generate_rule_completion(cube):
    output = []
    output.append('DB(\'{}\', '.format(cube.name))

    params = []
    for index, dimension in enumerate([dim for dim in cube.dimensions if dim != 'Sandboxes'], start=1):
        param_name = dimension.replace(' ', '')
        param_name = '\\' + param_name if param_name.startswith('}') else param_name
        params.append('${%s:!%s}' % (str(index), param_name))

    output.append(', '.join(params))
    output.append(')')

    clean = [(' ', '_'), ('.', '-'), ('}', '')]
    name = cube.name.upper()
    for k, v in clean:
        name = name.replace(k, v)

    return ["_DB-{}".format(name), ''.join(output)]


def view_to_process(view, process):
    if not process:
        file = os.path.basename(view.file_name())
        file, ext = os.path.splitext(file)
        process = Process(name=file)

    content = view.substr(sublime.Region(0, view.size()))
    content = content.replace('\r\n', '\n').strip('\n')
    content = content.split('\n')

    # Parse Sections
    sections = ['PARAMETERS', 'DATASOURCE', 'VARIABLES', 'PROLOG', 'METADATA', 'DATA', 'EPILOG']
    section_text = {}

    for section in sections:
        parse_section = section
        section_text[parse_section] = ''

        regex_find = re.compile('^(#+\s*?)?(' + parse_section + ')(:|;)')
        regex_end = re.compile('^(#+\s*?)?({})(:|;)'.format('|'.join(sections)))

        search_active = False

        for line in content:
            if search_active and not regex_end.search(line) and line.rstrip() != ProcessTemplate.COMMENT:
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
            sublime.message_dialog('An error occurred updating {}\n\n{}'.format(file, e))
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

    process.prolog_procedure = section_text['PROLOG'].strip('\n')
    process.metadata_procedure = section_text['METADATA'].strip('\n')
    process.data_procedure = section_text['DATA'].strip('\n')
    process.epilog_procedure = section_text['EPILOG'].strip('\n')

    return process


def highlight_errors(view, popup_message, line_number, procedure):
    if procedure:
        highlight_region = view.find('(### ' + procedure.upper() + ':)(.*?)(\n)', 0)
        for _ in range(1, line_number):
            highlight_region = view.find('(.*?)(\n)', highlight_region.b)
        highlight_region = sublime.Region(highlight_region.a, highlight_region.b - 1)
    else:
        highlight_region = view.line(
            sublime.Region(view.text_point(line_number - 1, 0), view.text_point(line_number - 1, 0)))

    view.add_regions('error', [highlight_region], "invalid")
    view.show(highlight_region, True)

    while not view.visible_region().contains(highlight_region):
        time.sleep(0.01)

    view.show_popup(popup_message, location=highlight_region.b)


def run_async(runnable):
    threading.Thread(daemon=True, target=runnable).start()
