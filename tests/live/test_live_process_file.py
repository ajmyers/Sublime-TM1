"""The .pro file against a real TM1: what Put would send is what TM1 has, and a process put from a
file comes back as the same file."""

import pytest

from tm1pkg.core.process_file import process_to_text, text_to_process

PREFIX = 'zz sublime-tm1 test '


def summary(items):
    return [(x.name, getattr(x, 'value', None), getattr(x, 'prompt', None), x.type) for x in items or []]


def test_reading_back_each_process_file_gives_what_tm1_has(tm1):
    processes = tm1.processes.list()
    assert processes
    for process in processes:
        back = text_to_process(process_to_text(process), process.name)
        assert summary(back.parameters) == summary(process.parameters), process.name
        assert summary(back.variables) == summary(process.variables), process.name
        server = dict(process.data_source.model_extra or {}, Type=process.data_source.type)
        mine = dict(back.data_source.model_extra or {}, Type=back.data_source.type)
        assert {k: server[k] for k in mine if k in server} == {k: mine[k] for k in mine if k in server}, process.name


@pytest.fixture
def scratch(tm1):
    names = []
    yield names
    for name in names:
        try:
            tm1.processes.delete(name)
        except Exception:
            pass


def put_copy(tm1, scratch, source):
    text = process_to_text(tm1.processes.get(source))
    name = PREFIX + str(len(scratch))
    scratch.append(name)
    text = text.replace('### Process: ' + source, '### Process: ' + name, 1)
    tm1.processes.create(text_to_process(text, name))
    return name, text


def test_a_process_put_from_its_file_comes_back_as_the_same_file(tm1, scratch):
    # An ASCII source with no header records: the code this replaced put them back as 1
    name, text = put_copy(tm1, scratch, 'create_Y2Ksales_cube')
    assert tm1.processes.compile(name) == []
    assert process_to_text(tm1.processes.get(name)) == text
    assert tm1.processes.get(name).data_source.model_extra['asciiHeaderRecords'] == 0


def test_updating_a_process_from_its_file(tm1, scratch):
    name, text = put_copy(tm1, scratch, 'create_Y2Ksales_cube')
    marker = '### PROLOG: ' + '#' * 67 + '\n\n'
    tm1.processes.update(name, text_to_process(text.replace(marker, marker + 'nSublime = 1;\n', 1), name))
    assert tm1.processes.get(name).prolog_procedure.startswith('nSublime = 1;')
