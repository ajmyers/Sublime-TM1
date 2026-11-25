"""core.threads: the console's thread table and log lines."""

import re
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


def test_lays_out_tm1tops_columns_aligned_with_a_cancel_link_per_thread():
    page = threads.thread_html([thread(7), thread(12, name='Bob', state='Wait', function='POST /api/v1/x')])
    head, first, second = re.findall(r'<div class="row[^"]*">(.*?)</div>', page)
    texts = [re.sub(r'<[^>]+>', '', row) for row in (head, first, second)]
    # Each column starts at the same character in every row: the panel's font is monospace
    assert texts[1].index('Admin') == texts[0].index('Name') == texts[2].index('Bob')
    assert texts[1].index('Run') == texts[0].index('State') == texts[2].index('Wait')
    assert 'href="cancel:7"' in first and 'href="cancel:12"' in second
    assert 'var(--greenish)' in first and 'var(--yellowish)' in second
    assert '<table' not in page


def test_escapes_what_tm1_sends():
    page = threads.thread_html([thread(1, function='<script>&', info='a\nb')])
    assert '<script>' not in page and '&lt;script&gt;&amp;' in page


def test_says_so_when_no_other_thread_runs():
    assert 'No other threads running.' in threads.thread_html([thread(2, function='GET /api/v1/Threads')])


def test_only_cancel_links_name_a_thread():
    assert threads.cancel_target('cancel:42') == 42
    assert threads.cancel_target('cancel:') is None and threads.cancel_target('https://x') is None


def test_formats_log_lines():
    entry = SimpleNamespace(time_stamp='2026-11-23 21:47:05.573000+00:00', level=SimpleNamespace(value='Info'),
                            logger='TM1.Process', message='hello')
    assert threads.log_lines([entry]) == ['2026-11-23 21:47:05.573  Info   TM1.Process         hello']
