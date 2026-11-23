"""core.process_file: the .pro file on skipcheck-tm1's models."""

import pytest
from skipcheck_tm1.model import ProcessDataSource, ProcessVariableType

import core_samples
from snapshot import matches_snapshot, read_snapshot
from tm1pkg.core.process_file import process_to_text, text_to_process

PROCESSES = {f.__name__: f for f in core_samples.ALL_PROCESSES}


@pytest.mark.parametrize('sample', PROCESSES)
def test_writes_the_same_file_as_before(sample):
    matches_snapshot(sample + '.pro', process_to_text(PROCESSES[sample]()))


@pytest.mark.parametrize('sample', PROCESSES)
def test_reading_the_file_back_writes_it_again_unchanged(sample):
    text = read_snapshot(sample + '.pro')
    assert process_to_text(text_to_process(text, PROCESSES[sample]().name)) == text


@pytest.mark.parametrize('sample', PROCESSES)
def test_reading_the_file_gives_back_the_process(sample):
    original = PROCESSES[sample]()
    process = text_to_process(process_to_text(original), original.name)

    assert process.name == original.name
    assert process.parameters == original.parameters
    assert process.variables == original.variables
    assert process.data_source.type == original.data_source.type
    assert process.data_source.model_extra == original.data_source.model_extra


def test_reads_a_file_with_windows_line_endings():
    text = read_snapshot('parameters_and_variables.pro')
    process = text_to_process(text.replace('\n', '\r\n'), 'Load Sales')
    assert process_to_text(process) == text


def test_goes_by_the_file_name_not_the_header():
    text = read_snapshot('cube_view.pro')
    assert text_to_process(text, 'Copy Plan v2').name == 'Copy Plan v2'


def test_types_parameters_by_their_value():
    process = text_to_process(read_snapshot('parameters_and_variables.pro'), 'Load Sales')
    assert [p.type for p in process.parameters] == [ProcessVariableType.STRING, ProcessVariableType.NUMERIC]


def test_fills_the_ascii_settings_a_file_leaves_out():
    text = read_snapshot('parameters_and_variables.pro').replace('###      ascii_thousand_separator: ","\n', '')
    extra = text_to_process(text, 'Load Sales').data_source.model_extra
    assert extra['asciiThousandSeparator'] == ','


def test_keeps_settings_that_are_zero_or_false():
    # The code this replaces left out every falsy setting and read them back as their defaults,
    # so no header records came back as 1 and a non-unicode ODBC source as unicode
    process = core_samples.odbc()
    process.data_source = ProcessDataSource(type='ODBC', dataSourceNameForServer='W', dataSourceNameForClient='W',
                                            userName='', password='', query='SELECT 1', usesUnicode=False)
    assert text_to_process(process_to_text(process), 'x').data_source.model_extra['usesUnicode'] is False

    process = core_samples.parameters_and_variables()
    process.data_source = ProcessDataSource(type='ASCII', dataSourceNameForServer='a.csv',
                                            dataSourceNameForClient='a.csv', asciiHeaderRecords=0,
                                            asciiDelimiterChar=',', **core_samples.ASCII_DEFAULTS)
    assert text_to_process(process_to_text(process), 'x').data_source.model_extra['asciiHeaderRecords'] == 0


def test_a_view_or_subset_is_one_object_for_client_and_server():
    client_row = '###      data_source_name_for_client: "Plan"'
    text = read_snapshot('cube_view.pro').replace(client_row, client_row.replace('Plan', 'Other'))
    extra = text_to_process(text, 'Copy Plan').data_source.model_extra
    assert extra['dataSourceNameForClient'] == extra['dataSourceNameForServer'] == 'Plan'


def test_a_fixed_width_file_has_no_delimiter_character():
    text = read_snapshot('parameters_and_variables.pro').replace('"Character"', '"FixedWidth"')
    assert 'asciiDelimiterChar' not in text_to_process(text, 'Load Sales').data_source.model_extra


def test_leaves_the_generated_statements_markers_out_of_the_file():
    assert 'Generated Statements' not in process_to_text(core_samples.no_datasource())


def test_a_process_with_nothing_set_writes_none_for_each_section():
    from skipcheck_tm1.model import Process
    text = process_to_text(Process(name='Empty'))
    assert text.count('###      None') == 3
