"""TM1: Run against a real TM1: the run's status, its own messages, its error file."""

from types import SimpleNamespace

from skipcheck_tm1.model import Process

from fakes import FakeView, FakeWindow

from tm1pkg.core.process_file import process_to_text, text_to_process
from tm1pkg.plugin import gateway, run

NAME = 'zz sublime-tm1 run test'


def test_runs_a_process_and_reads_its_messages_and_error_file(tm1):
    prolog = "LogOutput('INFO', 'hello from ' | pWho);\nItemReject('a minor error');"
    process = Process(name=NAME, prolog_procedure=prolog)
    text = process_to_text(process).replace('###      None', '###    - name: pWho\n###      value: "nobody"\n'
                                                              '###      prompt: ""', 1)
    tm1.processes.create(text_to_process(text, NAME))
    try:
        for async_requests in (True, False):
            status, messages, contents = run.execute(NAME, {'pWho': 'Sublime'}, async_requests)(tm1)
            assert status == 'CompletedWithMessages'
            texts = [m.message for m in messages]
            assert texts[0].startswith('Process "{}" executed by user'.format(NAME))
            assert 'hello from Sublime' in texts
            assert any('a minor error' in c for c in contents.values())
    finally:
        tm1.processes.delete(NAME)


class Gateway:
    """The gateway, on the live client: each piece of work runs at once."""

    def __init__(self, client):
        self.client, self.errors = client, []
        self.connection = SimpleNamespace(async_requests=True)

    def run(self, window, work, on_done=None, on_error=None):
        try:
            result = work(self.client)
        except Exception as e:
            self.errors.append(e)
            if on_error:
                on_error(e)
        else:
            on_done(result)


def test_choosing_a_process_asks_for_its_parameters(tm1, monkeypatch):
    prolog = "LogOutput('INFO', pWho);"
    text = process_to_text(Process(name=NAME, prolog_procedure=prolog)).replace(
        '###      None', '###    - name: pWho\n###      value: "nobody"\n###      prompt: "Who?"', 1)
    tm1.processes.create(text_to_process(text, NAME))
    try:
        tm1pkg_gateway = Gateway(tm1)
        monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: tm1pkg_gateway)
        window = FakeWindow(project={'folders': []}, project_file='/p/x.sublime-project')
        window.view = FakeView('', '/p/processes/{}.pro'.format(NAME))
        run.RunTurboIntegratorProcess(window).run()
        panel = window.quick_panels[0]
        panel['on_select'](panel['selected_index'])
        assert tm1pkg_gateway.errors == []
        assert window.panels[0].caption == 'pWho (Who?):'
        assert window.panels[0].text == 'nobody'
    finally:
        tm1.processes.delete(NAME)
