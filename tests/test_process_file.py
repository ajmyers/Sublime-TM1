"""The .pro file: what Get writes for a process, and what Put reads back from it."""

import pytest

import samples
from fakes import FakeView
from tm1pkg.pelle import Utils
from snapshot import matches_snapshot, read_snapshot

PROCESSES = {f.__name__: f for f in samples.ALL_PROCESSES}


def pro_file(name):
    return name + '.pro'


@pytest.mark.parametrize('sample', PROCESSES)
def test_writes_the_file_it_always_has(sample):
    matches_snapshot(pro_file(sample), Utils.process_to_text(PROCESSES[sample]()))


@pytest.mark.parametrize('sample', PROCESSES)
def test_reading_the_file_back_writes_it_again_unchanged(sample):
    text = read_snapshot(pro_file(sample))
    name = PROCESSES[sample]().name
    process = Utils.view_to_process(FakeView(text, '/project/processes/{}.pro'.format(name)), None)
    assert Utils.process_to_text(process) == text


@pytest.mark.parametrize('sample', PROCESSES)
def test_reading_the_file_gives_back_the_process(sample):
    original = PROCESSES[sample]()
    text = Utils.process_to_text(original)
    process = Utils.view_to_process(FakeView(text, '/p/{}.pro'.format(original.name)), None)

    assert process.name == original.name
    assert process.parameters == original.parameters
    assert [(v['Name'], v['Type']) for v in process.variables] == [(v['Name'], v['Type']) for v in original.variables]
    assert process.datasource_type == original.datasource_type
    for attribute in [a for a in dir(original) if a.startswith('datasource_')]:
        assert getattr(process, attribute) == getattr(original, attribute), attribute


def test_leaves_the_generated_statements_markers_out_of_the_file():
    assert 'Generated Statements' not in Utils.process_to_text(samples.no_datasource())


def test_reads_a_file_with_windows_line_endings():
    text = read_snapshot('parameters_and_variables.pro')
    process = Utils.view_to_process(FakeView(text.replace('\n', '\r\n'), '/p/Load Sales.pro'), None)
    assert Utils.process_to_text(process) == text


def test_put_reads_into_the_server_process_keeping_what_the_file_does_not_carry():
    server = samples.parameters_and_variables()
    server.add_parameter('pObsolete', '', 'x')
    text = read_snapshot('parameters_and_variables.pro')

    process = Utils.view_to_process(FakeView(text, '/p/Load Sales.pro'), server)

    assert process is server
    assert [p['Name'] for p in process.parameters] == ['pYear', 'pScale']
