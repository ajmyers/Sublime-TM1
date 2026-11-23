"""TM1: Put, on the gateway: the process or the rules from the file, and TM1's errors on their lines."""

from types import SimpleNamespace

import pytest
from skipcheck_tm1.errors import ODataError, Tm1ApiError, Tm1ErrorKind
from skipcheck_tm1.model import ProcessProcedure, ProcessSyntaxError, RuleSyntaxError

import core_samples
from fakes import FakeView, FakeWindow
from tm1pkg.core import process_file, rule_file
from tm1pkg.plugin import diagnostics, gateway, put


class FakeGateway:
    def __init__(self, client):
        self.client = client

    def run(self, window, work, on_done=None, on_error=None):
        on_done(work(self.client))


class Processes:
    def __init__(self, existing, errors=()):
        self.existing, self.errors, self.calls = existing, list(errors), []

    def get(self, name, **options):
        if name not in self.existing:
            raise Tm1ApiError.of_kind(404, Tm1ErrorKind.NOT_FOUND, ODataError(message='no'), 'GET', 'u')
        return SimpleNamespace(name=name)

    def create(self, process):
        self.calls.append(('create', process.name))

    def update(self, name, process):
        self.calls.append(('update', name))

    def compile(self, name):
        return self.errors


class Cubes:
    def __init__(self, errors=()):
        self.errors, self.calls = list(errors), []

    def update(self, name, cube):
        self.calls.append(('update', name, cube.rules))

    def check_rules(self, name):
        return self.errors


def put_in(view, client, monkeypatch):
    window = FakeWindow(project={'settings': {}}, project_file='/p/x.sublime-project')
    window.active_view = lambda: view
    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: FakeGateway(client))
    put.PutObjectToServer(window).run()
    return window


PROCESS = process_file.process_to_text(core_samples.cube_view())
BAD_PROCESS = PROCESS.replace('### DATA: ' + '#' * 69 + '\n\n', '### DATA: ' + '#' * 69 + '\n\n\nnOk = 1;\nnot TI;\n')


def test_updates_a_process_that_exists_and_says_so(monkeypatch):
    processes = Processes(existing={'Copy Plan'})
    view = FakeView(PROCESS, '/p/processes/Copy Plan.pro')
    window = put_in(view, SimpleNamespace(processes=processes), monkeypatch)
    assert processes.calls == [('update', 'Copy Plan')]
    assert window.statuses[-1] == 'TM1: process Copy Plan put, no errors'


def test_creates_a_process_that_doesnt_exist(monkeypatch):
    processes = Processes(existing=set())
    put_in(FakeView(PROCESS, '/p/processes/New One.pro'), SimpleNamespace(processes=processes), monkeypatch)
    assert processes.calls == [('create', 'New One')]


def test_shows_compile_errors_on_their_lines_in_the_file(monkeypatch):
    errors = [ProcessSyntaxError(procedure=ProcessProcedure.DATA, line_number=2, message='Syntax error: not TI')]
    view = FakeView(BAD_PROCESS, '/p/processes/Copy Plan.pro')
    window = put_in(view, SimpleNamespace(processes=Processes({'Copy Plan'}, errors)), monkeypatch)
    assert view.region_text(diagnostics.KEY) == ['not TI;']
    assert 'Syntax error: not TI' in view.regions[diagnostics.KEY]['annotations'][0]
    assert window.statuses[-1] == 'TM1: process Copy Plan put, with 1 error'


def test_puts_rules_and_shows_their_errors(monkeypatch):
    text = rule_file.rules_to_text('Sales', ['Region'], "SKIPCHECK;\n['A'] = N: 1;\nbroken\n")
    cubes = Cubes(errors=[RuleSyntaxError(line_number=text.split('\n').index('broken') + 1, message='bad')])
    view = FakeView(text, '/p/rules/Sales.rux')
    put_in(view, SimpleNamespace(cubes=cubes), monkeypatch)
    assert cubes.calls == [('update', 'Sales', rule_file.text_to_rules(text))]
    assert view.region_text(diagnostics.KEY) == ['broken']


def test_saves_the_file_first_and_clears_earlier_errors(monkeypatch):
    view = FakeView(PROCESS, '/p/processes/Copy Plan.pro')
    view.dirty = True
    put_in(view, SimpleNamespace(processes=Processes({'Copy Plan'})), monkeypatch)
    assert view.commands[0] == 'save'
    assert diagnostics.KEY in view.erased and diagnostics.LEGACY_KEY in view.erased


def test_is_enabled_only_for_processes_and_rules():
    for name, enabled in [('/p/a.pro', True), ('/p/a.rux', True), ('/p/a.txt', False), (None, False)]:
        window = FakeWindow()
        window.active_view = lambda n=name: FakeView('', n)
        assert put.PutObjectToServer(window).is_enabled() is enabled


@pytest.mark.parametrize('blank_lines', [1, 3])
def test_finds_the_line_after_any_blank_lines_under_the_header(blank_lines):
    text = PROCESS.replace('### DATA: ' + '#' * 69 + '\n\n', '### DATA: ' + '#' * 69 + '\n' + '\n' * blank_lines)
    line = process_file.error_line(text, 'Data', 1)
    assert text.split('\n')[line] == "CellPutN(Value, 'Forecast', v1, v2);"
