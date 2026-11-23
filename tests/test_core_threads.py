"""core.threads: the console's thread table and log lines."""

from types import SimpleNamespace

from tm1pkg.core import threads


def thread(ident, name='Admin', function='GET /api/v1/Cubes', **more):
    fields = dict(id=ident, type='User', name=name, state='Run', function=function, object_name='', r_locks=0,
                  ix_locks=0, w_locks=0, elapsed_time='P0D', wait_time='P0D', info='')
    fields.update(more)
    return SimpleNamespace(**fields)


def test_leaves_out_the_consoles_own_request_and_cam_ids():
    listed = [thread(1, 'Alice CAMID("OIDC:u:alice")'), thread(2, function='GET /api/v1/Threads')]
    rows = threads.rows(listed)
    assert [r[0] for r in rows] == [1] and rows[0][2] == 'Alice'


def test_draws_the_table_with_tm1tops_columns():
    text = threads.thread_table([thread(7)])
    assert 'ElapsedTime' in text.splitlines()[1] and '| 7 ' in text


def test_formats_log_lines():
    entry = SimpleNamespace(time_stamp='2026-11-23 21:47:05.573000+00:00', level=SimpleNamespace(value='Info'),
                            logger='TM1.Process', message='hello')
    assert threads.log_lines([entry]) == ['2026-11-23 21:47:05.573  Info   TM1.Process         hello']
