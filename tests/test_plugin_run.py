"""TM1: Run, on the gateway: choose, ask the parameters, confirm, run, report."""

import os
from types import SimpleNamespace

import pytest

from fakes import FakeView, FakeWindow
from tm1pkg.plugin import gateway, run


class FakeGateway:
    def __init__(self, client):
        self.client = client
        self.connection = SimpleNamespace(async_requests=True)

    def run(self, window, work, on_done=None, on_error=None):
        on_done(work(self.client))


def parameter(name, value, kind, prompt=''):
    return SimpleNamespace(name=name, value=value, type=SimpleNamespace(value=kind), prompt=prompt)


@pytest.fixture
def world(tmp_path, monkeypatch):
    executed = []
    process = SimpleNamespace(name='Load Sales', parameters=[parameter('pYear', '2024', 'String', 'Year'),
                                                              parameter('pScale', 1000, 'Numeric')])
    client = SimpleNamespace(processes=SimpleNamespace(list=lambda **o: [SimpleNamespace(name=n) for n in
                                                                          ['Archive', 'Load Sales', 'Sales.Caller']],
                                                       get=lambda name, **o: process))
    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: FakeGateway(client))

    def execute(name, parameters, async_requests=True):
        def work(c):
            executed.append((name, parameters))
            return 'CompletedWithMessages', [SimpleNamespace(time_stamp='t', level='Info', logger='TM1.Process',
                                                            message='hello')], {'TM1ProcessError_x.log': 'line 2 bad'}
        return work

    monkeypatch.setattr(run, 'execute', execute)
    logs = tmp_path / 'logs'
    logs.mkdir()
    window = FakeWindow(project={'folders': [{'name': run.LOG_FOLDER, 'path': str(logs)}]},
                        project_file='/p/x.sublime-project')
    window.view = FakeView('', '/p/processes/Load Sales.pro')
    return window, executed, logs


def test_lists_callers_first_with_the_current_process_selected(world):
    window, _, _ = world
    run.RunTurboIntegratorProcess(window).run()
    panel = window.quick_panels[0]
    assert panel['items'] == ['Sales.Caller', 'Archive', 'Load Sales'] and panel['selected_index'] == 2


def test_asks_each_parameter_confirms_and_runs_with_numbers_as_numbers(world):
    window, executed, logs = world
    run.RunTurboIntegratorProcess(window).run()
    window.quick_panels[0]['on_select'](2)
    assert window.panels[0].caption == 'pYear (Year):'
    window.panels[0].type('5')  # 2024 -> 20245
    window.panels[0].submit()
    window.panels[1].submit()
    window.quick_panels[1]['on_select'](0)
    assert executed == [('Load Sales', {'pYear': '20245', 'pScale': 1000})]
    output = window.outputs[run.PANEL].text
    assert 'Process : Load Sales' in output and 'pScale : 1000' in output
    assert 'Process completed with status: CompletedWithMessages' in output and 'line 2 bad' in output
    folder = next(logs.iterdir())
    assert sorted(os.listdir(folder)) == ['TM1ProcessError_x.log', '_run.txt', '_tm1server.log']


def test_cancelling_at_the_confirmation_runs_nothing(world):
    window, executed, _ = world
    run.RunTurboIntegratorProcess(window).run()
    window.quick_panels[0]['on_select'](1)  # Archive: no parameters of its own here, same fake
    window.panels[0].submit()
    window.panels[1].submit()
    window.quick_panels[1]['on_select'](1)
    assert executed == []


def test_called_with_arguments_it_runs_at_once_as_0_2_did(world):
    window, executed, _ = world
    run.RunTurboIntegratorProcess(window).run(process='Load Sales', confirm='Yes', pYear='2023')
    assert executed == [('Load Sales', {'pYear': '2023'})] and window.quick_panels == []


def test_clearing_the_logs_takes_the_folder_out_of_the_project(world):
    window, _, logs = world
    window.project['folders'].append({'name': 'Model', 'path': str(logs.parent)})
    run.ClearTurboIntegratorLogs(window).run()
    assert [f['name'] for f in window.project['folders']] == ['Model']
