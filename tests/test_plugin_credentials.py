"""plugin.credentials: passwords asked at first use, shown masked, kept in memory."""

import pytest

from fakes import FakeWindow
from tm1pkg.core.connection import Connection
from tm1pkg.plugin import credentials
from tm1pkg.plugin.credentials import MASK, unmask

CONNECTION = Connection(address='tm1', port='8010', user='admin')


@pytest.fixture(autouse=True)
def no_passwords():
    credentials.forget_all()
    yield
    credentials.forget_all()


def test_unmask_appends_what_was_typed():
    assert unmask('', 'a') == 'a'
    assert unmask('ab', MASK * 2 + 'c') == 'abc'


def test_unmask_takes_a_deletion_to_be_at_the_end():
    assert unmask('abc', MASK * 2) == 'ab'
    assert unmask('abc', '') == ''


def test_unmask_keeps_a_paste():
    assert unmask('ab', MASK * 2 + 'cdef') == 'abcdef'


def test_the_panel_shows_only_bullets_and_gives_the_real_password():
    window, got = FakeWindow(), []
    credentials.ask_secret(window, 'Password:', got.append)
    panel = window.panels[0]
    panel.type('apple')
    assert panel.text == MASK * 5
    panel.backspace()
    panel.type('e!')
    panel.submit()
    assert got == ['apple!']
    assert panel.settings()['spell_check'] is False


def test_asks_once_per_project_then_remembers():
    window, got = FakeWindow(), []
    credentials.with_password(window, '/p/a.sublime-project', CONNECTION, got.append)
    assert 'admin at http://tm1:8010/api/v1/' in window.panels[0].caption
    window.panels[0].type('apple')
    window.panels[0].submit()
    credentials.with_password(window, '/p/a.sublime-project', CONNECTION, got.append)
    assert got == ['apple', 'apple'] and len(window.panels) == 1


def test_each_project_has_its_own_password():
    window, got = FakeWindow(), []
    credentials.with_password(window, '/p/a.sublime-project', CONNECTION, got.append)
    credentials.with_password(window, '/p/b.sublime-project', CONNECTION, got.append)
    assert len(window.panels) == 2


def test_cancelling_calls_nothing_but_on_cancel():
    window, got, cancelled = FakeWindow(), [], []
    credentials.with_password(window, '/p/a.sublime-project', CONNECTION, got.append, lambda: cancelled.append(1))
    window.panels[0].cancel()
    assert got == [] and cancelled == [1] and not credentials.known('/p/a.sublime-project')
