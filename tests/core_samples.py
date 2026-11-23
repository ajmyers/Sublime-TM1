"""The samples of tests/samples.py as skipcheck-tm1 models, the way TM1's REST API returns them.

The snapshots in tests/snapshots/ were written from the TM1py samples by the code this replaces;
these must write the same files.
"""

from skipcheck_tm1.model import Process, ProcessDataSource, ProcessParameter, ProcessVariable

# TM1 returns every ASCII setting, set or not
ASCII_DEFAULTS = dict(asciiDecimalSeparator='.', asciiDelimiterType='Character', asciiThousandSeparator=',')


def no_datasource():
    return Process(
        name='}tm1.Housekeeping',
        prolog_procedure=(
            '#****Begin: Generated Statements***\n#****End: Generated Statements****\n\n'
            "sMsg = 'Hello';\nLogOutput('INFO', sMsg);"
        ),
        metadata_procedure='', data_procedure='', epilog_procedure='',
        data_source=ProcessDataSource(type='None'), parameters=[], variables=[],
    )


def parameters_and_variables():
    return Process(
        name='Load Sales',
        data_source=ProcessDataSource(
            type='ASCII', dataSourceNameForServer='/data/sales.csv', dataSourceNameForClient='C:\\data\\sales.csv',
            asciiDelimiterChar=',', asciiQuoteCharacter='"', asciiHeaderRecords=1, **ASCII_DEFAULTS),
        prolog_procedure="IF(pYear @= '');\n   ProcessQuit;\nENDIF;",
        metadata_procedure='',
        data_procedure="CellPutN(vValue, 'Sales', vRegion, pYear, 'Amount');",
        epilog_procedure='\r\n# CRLF line endings\r\nnDone = 1;\r\n',
        parameters=[
            ProcessParameter(name='pYear', prompt='Year to load, e.g. "2024"', value='2024', type='String'),
            ProcessParameter(name='pScale', prompt='Scale – ünïcode prompt', value=1000, type='Numeric'),
        ],
        variables=[
            ProcessVariable(name='vRegion', type='String', position=1, start_byte=0, end_byte=0),
            ProcessVariable(name='vValue', type='Numeric', position=2, start_byte=0, end_byte=0),
        ],
    )


def cube_view():
    return Process(
        name='Copy Plan',
        data_source=ProcessDataSource(type='TM1CubeView', dataSourceNameForServer='Plan',
                                      dataSourceNameForClient='Plan', view='}Export'),
        prolog_procedure='', metadata_procedure='', epilog_procedure='',
        data_procedure="CellPutN(Value, 'Forecast', v1, v2);",
        parameters=[], variables=[],
    )


def odbc():
    return Process(
        name='Extract Orders',
        data_source=ProcessDataSource(type='ODBC', dataSourceNameForServer='Warehouse',
                                      dataSourceNameForClient='Warehouse', userName='etl', password='',
                                      query="SELECT region, amount\nFROM orders\nWHERE year = '2024'",
                                      usesUnicode=True),
        prolog_procedure='', metadata_procedure='', data_procedure='', epilog_procedure='',
        parameters=[], variables=[],
    )


def subset():
    return Process(
        name='Iterate Regions',
        data_source=ProcessDataSource(type='TM1DimensionSubset', dataSourceNameForServer='Region',
                                      dataSourceNameForClient='Region', subset='All Leaves'),
        prolog_procedure='', metadata_procedure='', data_procedure='', epilog_procedure='',
        parameters=[], variables=[],
    )


ALL_PROCESSES = [no_datasource, parameters_and_variables, cube_view, odbc, subset]

SALES_RULES = "SKIPCHECK;\n\n['Margin'] = N: ['Revenue'] - ['Cost'];\n\nFEEDERS;\n"
CUBES = {
    'sales_cube': ('Sales', ['Region', 'Year', 'Measure', 'Sandboxes'], SALES_RULES),
    'control_cube': ('}ClientGroups', ['}Clients', '}Groups'], "['Admin'] = S: 'ADMIN';"),
}
