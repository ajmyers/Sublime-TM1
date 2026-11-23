"""TM1: Run against a real TM1: the run's status, its own messages, its error file."""

from skipcheck_tm1.model import Process

from tm1pkg.core.process_file import process_to_text, text_to_process
from tm1pkg.plugin import run

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
