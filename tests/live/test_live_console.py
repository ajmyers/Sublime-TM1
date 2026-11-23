"""The console against a real TM1: a long process's thread is listed, and cancelling it ends it."""

import threading
import time

from skipcheck_tm1.model import Process

from tm1pkg.core import threads as tm1_threads

NAME = 'zz sublime-tm1 console test'


def test_lists_a_running_process_thread_and_cancels_it(tm1):
    import os

    from skipcheck_tm1 import Tm1Client

    tm1.processes.create(Process(name=NAME, prolog_procedure='nI = 0;\nWHILE(nI < 1000000000);\n   nI = nI + 1;\nEND;'))
    runner = Tm1Client.builder().base_url(os.environ['TM1_URL']).basic_auth(
        os.environ.get('TM1_USER', 'admin'), os.environ.get('TM1_PASSWORD', '')).build()
    outcome = {}
    started = threading.Thread(target=lambda: outcome.update(result=_run(runner)))
    started.start()
    try:
        deadline, mine = time.time() + 20, None
        while time.time() < deadline and mine is None:
            listed = tm1_threads.others(tm1.threads.list())
            text = lambda t: (t.object_name or '') + (t.function or '') + (t.info or '')  # noqa: E731
            mine = next((t for t in listed if NAME in text(t)), None)
            time.sleep(0.5)
        assert mine is not None, [(t.function, t.object_name) for t in listed]
        tm1.threads.cancel(int(mine.id))
        started.join(60)
        assert not started.is_alive()
        # TM1 ends the run's request with "TM1UserException: Cancel [code 174]"
        assert 'Cancel [code 174]' in outcome['result'], outcome['result']
    finally:
        runner.close()
        tm1.processes.delete(NAME)


def _run(client):
    try:
        return client.processes.execute_with_return(NAME).process_execute_status_code.value
    except Exception as e:
        return 'error: {}'.format(e)
