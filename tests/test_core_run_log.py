"""core.run_log and core.table: one run's messages, and plain-text tables."""

from types import SimpleNamespace

from tm1pkg.core import run_log
from tm1pkg.core.table import table


def entry(thread, message, user='Admin'):
    return SimpleNamespace(thread_id=thread, message=message.replace('{user}', user))


def test_takes_the_latest_run_on_its_thread_from_its_start_to_its_end():
    entries = [
        entry(1, 'Process "Load": finished executing normally.'),  # an earlier run on a reused thread
        entry(2, 'Process "Load" executed by user "{user}"', user='Bob'),
        entry(1, 'Process "Load" executed by user "{user}"'),
        entry(2, 'something of Bob\'s run'),
        entry(1, 'hello from Load'),
        entry(1, 'Process "Load":  finished executing normally. Error file: <TM1ProcessError_1_Load.log>'),
        entry(1, 'a later request on the same thread'),
    ]
    run = run_log.run_messages(entries, 'Load', user='Admin')
    assert [e.message for e in run] == [entries[2].message, 'hello from Load', entries[5].message]
    assert run_log.error_files(run) == ['TM1ProcessError_1_Load.log']


def test_no_run_found_is_no_messages():
    assert run_log.run_messages([entry(1, 'unrelated')], 'Load') == []


def test_lists_callers_first():
    names = ['Load Sales', 'Sales.Caller', 'Archive', 'call.monthly']
    assert run_log.callers_first(names) == ['Sales.Caller', 'call.monthly', 'Load Sales', 'Archive']


def test_lays_out_a_table():
    assert table(['ID', 'Name'], [[1, 'Admin'], [12, None]]) == 'ID  Name\n--  -----\n1   Admin\n12'
    framed = table(['A'], [['x']], border=True)
    assert framed.splitlines() == ['+---+', '| A |', '+---+', '| x |', '+---+']


def test_orders_entries_of_one_millisecond_by_their_id_and_knows_a_complete_run():
    finished = SimpleNamespace(time_stamp=1, id='12', thread_id=1, message='Process "Load":  finished executing')
    started = SimpleNamespace(time_stamp=1, id='10', thread_id=1, message='Process "Load" executed by user "A"')
    hello = SimpleNamespace(time_stamp=1, id='11', thread_id=1, message='hello')
    entries = sorted([finished, hello, started], key=run_log.order)
    assert entries == [started, hello, finished]
    run = run_log.run_messages(entries, 'Load')
    assert run_log.complete(run, 'Load') and not run_log.complete(run[:2], 'Load')
