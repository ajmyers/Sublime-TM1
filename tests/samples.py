"""Sample processes and cubes covering what the .pro and .rux files carry.

They're TM1py objects for now, as the plugin's file conversion is written against TM1py. The
snapshots in tests/snapshots/ are the files the plugin writes for them today: whatever replaces
TM1py must write the same files, so existing projects keep working.
"""

from TM1py import Cube, Process
from TM1py.Objects.Rules import Rules


def no_datasource():
    return Process(
        name='}tm1.Housekeeping',
        prolog_procedure=(
            '#****Begin: Generated Statements***\n#****End: Generated Statements****\n\n'
            "sMsg = 'Hello';\nLogOutput('INFO', sMsg);"
        ),
        epilog_procedure='',
    )


def parameters_and_variables():
    process = Process(
        name='Load Sales',
        datasource_type='ASCII',
        datasource_data_source_name_for_server='/data/sales.csv',
        datasource_data_source_name_for_client='C:\\data\\sales.csv',
        datasource_ascii_delimiter_char=',',
        datasource_ascii_quote_character='"',
        datasource_ascii_header_records=1,
        prolog_procedure="IF(pYear @= '');\n   ProcessQuit;\nENDIF;",
        metadata_procedure='',
        data_procedure="CellPutN(vValue, 'Sales', vRegion, pYear, 'Amount');",
        epilog_procedure='\r\n# CRLF line endings\r\nnDone = 1;\r\n',
    )
    process.add_parameter('pYear', 'Year to load, e.g. "2024"', '2024')
    process.add_parameter('pScale', 'Scale – ünïcode prompt', 1000)
    process.add_variable('vRegion', 'String')
    process.add_variable('vValue', 'Numeric')
    return process


def cube_view():
    return Process(
        name='Copy Plan',
        datasource_type='TM1CubeView',
        datasource_data_source_name_for_server='Plan',
        datasource_data_source_name_for_client='Plan',
        datasource_view='}Export',
        data_procedure="CellPutN(Value, 'Forecast', v1, v2);",
    )


def odbc():
    return Process(
        name='Extract Orders',
        datasource_type='ODBC',
        datasource_data_source_name_for_server='Warehouse',
        datasource_data_source_name_for_client='Warehouse',
        datasource_user_name='etl',
        datasource_query="SELECT region, amount\nFROM orders\nWHERE year = '2024'",
    )


def subset():
    return Process(
        name='Iterate Regions',
        datasource_type='TM1DimensionSubset',
        datasource_data_source_name_for_server='Region',
        datasource_data_source_name_for_client='Region',
        datasource_subset='All Leaves',
    )


ALL_PROCESSES = [no_datasource, parameters_and_variables, cube_view, odbc, subset]


def sales_cube(rules='SKIPCHECK;\n\n[\'Margin\'] = N: [\'Revenue\'] - [\'Cost\'];\n\nFEEDERS;\n'):
    return Cube(name='Sales', dimensions=['Region', 'Year', 'Measure', 'Sandboxes'], rules=Rules(rules))


def control_cube():
    return Cube(name='}ClientGroups', dimensions=['}Clients', '}Groups'], rules=Rules("['Admin'] = S: 'ADMIN';"))


ALL_CUBES = [sales_cube, control_cube]
