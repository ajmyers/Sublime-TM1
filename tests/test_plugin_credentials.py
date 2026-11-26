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



PROJECT = {'settings': {'tm1': {'address': 'tm1', 'port': '8010', 'user': 'admin'}}}


def project_window(remember=None):
    project = {'settings': {'tm1': dict(PROJECT['settings']['tm1'])}}
    if remember is not None:
        project['settings']['tm1'][credentials.REMEMBER] = remember
    return FakeWindow(project=project, project_file='/p/a.sublime-project')


def typed(window, password='apple'):
    got = []
    credentials.with_password(window, '/p/a.sublime-project', CONNECTION, got.append)
    window.panels[-1].type(password)
    window.panels[-1].submit()
    return got


def test_offers_to_remember_once_tm1_accepts_and_keeps_the_answer(credential_store):
    window = project_window()
    typed(window)
    assert window.quick_panels == []  # nothing stored or offered before TM1 takes it
    credentials.accepted(window, '/p/a.sublime-project', CONNECTION)
    assert 'Keychain' in window.quick_panels[0]['items'][0].trigger
    window.quick_panels[0]['on_select'](0)
    assert credential_store.secrets == {'admin at http://tm1:8010/api/v1/': 'apple'}
    assert window.project_data()['settings']['tm1'][credentials.REMEMBER] is True


def test_ask_each_session_is_kept_and_not_offered_again(credential_store):
    window = project_window()
    typed(window)
    credentials.accepted(window, '/p/a.sublime-project', CONNECTION)
    window.quick_panels[0]['on_select'](1)
    assert credential_store.secrets == {} and window.project_data()['settings']['tm1'][credentials.REMEMBER] is False
    credentials.forget_all()
    typed(window)
    credentials.accepted(window, '/p/a.sublime-project', CONNECTION)
    assert len(window.quick_panels) == 1


def test_a_remembered_password_is_used_without_asking(credential_store):
    credential_store.secrets['admin at http://tm1:8010/api/v1/'] = 'stored'
    window, got = project_window(remember=True), []
    credentials.with_password(window, '/p/a.sublime-project', CONNECTION, got.append)
    assert got == ['stored'] and window.panels == []


def test_a_refused_password_leaves_the_store_and_the_next_one_is_stored(credential_store):
    credential_store.secrets['admin at http://tm1:8010/api/v1/'] = 'old'
    window = project_window(remember=True)
    credentials.with_password(window, '/p/a.sublime-project', CONNECTION, lambda p: None)
    credentials.rejected('/p/a.sublime-project', CONNECTION)
    assert credential_store.secrets == {}
    typed(window, 'new')
    credentials.accepted(window, '/p/a.sublime-project', CONNECTION)
    assert credential_store.secrets == {'admin at http://tm1:8010/api/v1/': 'new'} and window.quick_panels == []


def test_a_failing_store_never_blocks(credential_store, capsys):
    credential_store.fail = True
    window = project_window(remember=True)
    got = typed(window)  # reading failed: asked instead
    assert got == ['apple']
    credentials.accepted(window, '/p/a.sublime-project', CONNECTION)  # storing fails: printed, no error
    credentials.rejected('/p/a.sublime-project', CONNECTION)
    assert 'credential store could not' in capsys.readouterr().out


def test_not_offered_without_a_store_or_a_place_for_the_answer(credential_store, monkeypatch):
    from tm1pkg.core import keychain

    legacy = FakeWindow(project={'settings': {'tm1_connection': {'address': 'tm1', 'port': '8010'}}},
                        project_file='/p/a.sublime-project')
    typed(legacy)
    credentials.accepted(legacy, '/p/a.sublime-project', CONNECTION)
    assert legacy.quick_panels == []
    credentials.forget_all()
    monkeypatch.setattr(keychain, '_store', lambda platform=None: None)
    window = project_window()
    typed(window)
    credentials.accepted(window, '/p/a.sublime-project', CONNECTION)
    assert window.quick_panels == []



def test_the_store_is_read_off_the_ui_thread(credential_store, monkeypatch):
    queued = []
    monkeypatch.setattr(credentials, '_background', queued.append)
    credential_store.secrets['admin at http://tm1:8010/api/v1/'] = 'stored'
    window, got = project_window(remember=True), []
    credentials.with_password(window, '/p/a.sublime-project', CONNECTION, got.append)
    assert got == [] and window.panels == []  # nothing read on the UI thread
    queued.pop()()
    assert got == ['stored']
