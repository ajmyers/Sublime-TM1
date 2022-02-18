import json

TEMPLATE = '''
###############################################################################
### Process: {name}
###############################################################################

###############################################################################
### PARAMETERS:
{parameters}
###############################################################################

###############################################################################
### DATASOURCE:
{datasource}
###############################################################################

###############################################################################
### VARIABLES:
{variables}
###############################################################################

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
'''.lstrip('\n')

DATASOURCE_KEYS = {
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

DATASOURCE_ROW = '###      {}: {}'
DATASOURCE_ROW_NONE = '###      None'

VARIABLES_ROW = '###    - name: {} ({})'
VARIABLES_ROW_NONE = '###      None'

GENERATED_STATEMENTS = [
    '#****Begin: Generated Statements***',
    '#****End: Generated Statements****',
    '#****GENERATED STATEMENTS START****',
    '#****GENERATED STATEMENTS FINISH****'
]

COMMENT = '###############################################################################'


def clean_procedure(procedure):
    procedure = procedure.replace('\r\n', '\n')
    for statement in GENERATED_STATEMENTS:
        procedure = procedure.replace(statement, '')
    procedure = procedure.strip('\n')
    return procedure


def generate_parameters(parameters):
    output = []
    if not parameters:
        output.append('###      None')
    else:
        for parameter in parameters:
            output.append('###    - name: {}'.format(parameter['Name']))
            output.append('###      value: {}'.format(json.dumps(parameter['Value'], ensure_ascii=False)))
            output.append('###      prompt: {}'.format(json.dumps(parameter['Prompt'], ensure_ascii=False)))

    return '\n'.join(output)


def generate_datasource(process):
    output = []
    if process.datasource_type == 'None':
        output.append(DATASOURCE_ROW_NONE)
    elif process.datasource_type in DATASOURCE_KEYS:
        for item in DATASOURCE_KEYS[process.datasource_type]:
            attribute = getattr(process, '_datasource_{}'.format(item), '')
            if attribute:
                attribute = json.dumps(attribute, ensure_ascii=False)
                output.append(DATASOURCE_ROW.format(item, attribute))
    else:
        for item in [x for x in dir(process) if x.startswith('_datasource_')]:
            attribute = getattr(process, item, '')
            if attribute:
                attribute = json.dumps(attribute, ensure_ascii=False)
                output.append(DATASOURCE_ROW.format(item[12:], attribute))

    return '\n'.join(output)


def generate_variables(variables):
    output = []
    if not variables:
        output.append(VARIABLES_ROW_NONE)
    else:
        for variable in variables:
            output.append(VARIABLES_ROW.format(variable['Name'], variable['Type']))

    return '\n'.join(output)


