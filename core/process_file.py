"""The .pro file: a TM1 process as text, which Get writes and Put reads back.

The format predates this module and users' projects are full of these files, so it's kept exactly:
tests/snapshots holds files this module must write byte for byte.

A process is a ``skipcheck_tm1.model.Process``. Its data source keeps the REST API's names
(``dataSourceNameForServer``); the file writes them in snake case (``data_source_name_for_server``).
"""

import json
import re

import yaml
from skipcheck_tm1.model import Process, ProcessDataSource, ProcessParameter, ProcessVariable, ProcessVariableType

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

COMMENT = '#' * 79
NONE_ROW = '###      None'

# The data source settings each type writes, in the order the file has them
DATASOURCE_KEYS = {
    'ASCII': ['type', 'data_source_name_for_client', 'data_source_name_for_server', 'ascii_decimal_separator',
              'ascii_delimiter_char', 'ascii_delimiter_type', 'ascii_header_records', 'ascii_quote_character',
              'ascii_thousand_separator'],
    'TM1CubeView': ['type', 'data_source_name_for_client', 'data_source_name_for_server', 'view'],
    'ODBC': ['type', 'data_source_name_for_client', 'data_source_name_for_server', 'user_name', 'password', 'query',
             'uses_unicode'],
    'TM1DimensionSubset': ['type', 'data_source_name_for_client', 'data_source_name_for_server', 'subset'],
}

# What a type's settings are when the file leaves them out: what TM1 Architect and TM1py used
DATASOURCE_DEFAULTS = {
    'ASCII': {'asciiDecimalSeparator': '.', 'asciiDelimiterChar': ';', 'asciiDelimiterType': 'Character',
              'asciiHeaderRecords': 1, 'asciiQuoteCharacter': '', 'asciiThousandSeparator': ',',
              'dataSourceNameForClient': '', 'dataSourceNameForServer': ''},
    'ODBC': {'dataSourceNameForClient': '', 'dataSourceNameForServer': '', 'userName': '', 'password': '',
             'query': '', 'usesUnicode': True},
    'TM1CubeView': {'dataSourceNameForServer': '', 'view': ''},
    'TM1DimensionSubset': {'dataSourceNameForServer': '', 'subset': ''},
}

# Markers TM1 adds around the statements its editors generate; TM1 puts them back on save
GENERATED_STATEMENTS = [
    '#****Begin: Generated Statements***',
    '#****End: Generated Statements****',
    '#****GENERATED STATEMENTS START****',
    '#****GENERATED STATEMENTS FINISH****',
]

SECTIONS = ['PARAMETERS', 'DATASOURCE', 'VARIABLES', 'PROLOG', 'METADATA', 'DATA', 'EPILOG']
SECTION_START = re.compile(r'^(#+\s*?)?({})(:|;)'.format('|'.join(SECTIONS)))


def snake_case(name):
    return re.sub(r'(?<!^)([A-Z])', r'_\1', name).lower()


def camel_case(name):
    first, *rest = name.split('_')
    return first + ''.join(word.capitalize() for word in rest)


# Writing


def process_to_text(process):
    """The .pro file for a process read from TM1."""
    procedures = [_clean_procedure(p) for p in (process.prolog_procedure, process.metadata_procedure,
                                                 process.data_procedure, process.epilog_procedure)]
    return TEMPLATE.format(
        name=process.name,
        parameters=_parameters_text(process.parameters or []),
        datasource=_datasource_text(process.data_source),
        variables=_variables_text(process.variables or []),
        prolog=procedures[0], metadata=procedures[1], data=procedures[2], epilog=procedures[3],
    )


def _clean_procedure(procedure):
    procedure = (procedure or '').replace('\r\n', '\n')
    for statement in GENERATED_STATEMENTS:
        procedure = procedure.replace(statement, '')
    return procedure.strip('\n')


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _parameters_text(parameters):
    if not parameters:
        return NONE_ROW
    rows = []
    for parameter in parameters:
        rows.append('###    - name: {}'.format(parameter.name))
        rows.append('###      value: {}'.format(_json(parameter.value)))
        rows.append('###      prompt: {}'.format(_json(parameter.prompt)))
    return '\n'.join(rows)


def _datasource_settings(data_source):
    """The data source's settings by their file names, the type first."""
    if data_source is None:
        return {'type': 'None'}
    settings = {'type': data_source.type or 'None'}
    for name, value in (data_source.model_extra or {}).items():
        settings[snake_case(name)] = value
    return settings


def _datasource_text(data_source):
    settings = _datasource_settings(data_source)
    kind = settings['type']
    if kind == 'None':
        return NONE_ROW
    keys = DATASOURCE_KEYS.get(kind, list(settings))
    # A setting TM1 leaves out or empty isn't written: reading the file back gives its default
    rows = ['###      {}: {}'.format(key, _json(settings[key])) for key in keys
            if settings.get(key) is not None and settings.get(key) != '']
    return '\n'.join(rows)


def _variables_text(variables):
    if not variables:
        return NONE_ROW
    return '\n'.join('###    - name: {} ({})'.format(v.name, _variable_type(v).value) for v in variables)


def _variable_type(variable):
    return variable.type if variable.type in (ProcessVariableType.STRING, ProcessVariableType.NUMERIC) \
        else ProcessVariableType.STRING


# Reading


def text_to_process(text, name):
    """The process a .pro file describes, to create or update on TM1. ``name`` is the file's name
    without .pro: the name in the file's header isn't read, as Put has always gone by the file name."""
    sections = _sections(text)

    parameters = _yaml(sections['PARAMETERS']) or []
    datasource = _yaml(sections['DATASOURCE']) or {'type': 'None'}
    variables = _yaml(sections['VARIABLES']) or []

    return Process(
        name=name,
        parameters=[_parameter(p) for p in parameters],
        data_source=_data_source(datasource),
        variables=[_variable(v, position) for position, v in enumerate(variables, start=1)],
        prolog_procedure=sections['PROLOG'].strip('\n'),
        metadata_procedure=sections['METADATA'].strip('\n'),
        data_procedure=sections['DATA'].strip('\n'),
        epilog_procedure=sections['EPILOG'].strip('\n'),
    )


def _sections(text):
    lines = text.replace('\r\n', '\n').strip('\n').split('\n')
    sections = {section: '' for section in SECTIONS}
    current = None
    for line in lines:
        match = SECTION_START.search(line)
        if match:
            current = match.group(2)
            continue
        if current and line.rstrip() != COMMENT:
            sections[current] += line.rstrip() + '\n'
    for section in ('PARAMETERS', 'DATASOURCE', 'VARIABLES'):
        sections[section] = sections[section].replace('### ', '')
    return sections


def _yaml(text):
    value = yaml.safe_load(text)
    return None if value == 'None' else value


def _parameter(parameter):
    value = parameter['value']
    kind = ProcessVariableType.STRING if isinstance(value, str) else ProcessVariableType.NUMERIC
    return ProcessParameter(name=parameter['name'], prompt=parameter['prompt'], value=value, type=kind)


def _data_source(settings):
    kind = settings.get('type', 'None')
    if kind == 'None':
        return ProcessDataSource(type='None')
    body = dict(DATASOURCE_DEFAULTS.get(kind, {}))
    body.update({camel_case(key): value for key, value in settings.items() if key != 'type'})
    if kind in ('TM1CubeView', 'TM1DimensionSubset'):
        # The client and server names are one object on TM1 itself
        body['dataSourceNameForClient'] = body['dataSourceNameForServer']
    if kind == 'ASCII' and body.get('asciiDelimiterType') == 'FixedWidth':
        body.pop('asciiDelimiterChar', None)
    return ProcessDataSource(type=kind, **body)


def _variable(variable, position):
    name = variable['name']
    if '(Numeric)' in name:
        kind, name = ProcessVariableType.NUMERIC, name.replace('(Numeric)', '')
    else:
        kind, name = ProcessVariableType.STRING, name.replace('(String)', '')
    return ProcessVariable(name=name.strip(), type=kind, position=position, start_byte=0, end_byte=0)


def error_line(text, procedure, line_number):
    """The 0-based line of the file that TM1's compile error points at: ``line_number`` of the
    procedure (Prolog, Metadata, Data, Epilog), counted from its first line as the file holds it
    (after the blank lines that follow the section's header). None if the file has no such section."""
    lines = text.replace('\r\n', '\n').split('\n')
    section = str(procedure).upper()
    for index, line in enumerate(lines):
        match = SECTION_START.search(line)
        if match and match.group(2) == section:
            first = index + 1
            while first < len(lines) and not lines[first].strip():
                first += 1
            return min(first + line_number - 1, len(lines) - 1)
    return None
