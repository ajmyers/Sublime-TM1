"""core.keychain: the OS credential store. A failure is printed, never raised."""

import os
import shutil
import sys

import pytest

from tm1pkg.core import keychain

ACCOUNT = 'LDAP\\test at http://tm1-keychain-test:1/api/v1/'


def test_a_failing_store_answers_none_or_false_and_says_why(credential_store, capsys):
    credential_store.fail = True
    assert keychain.get(ACCOUNT) is None
    assert keychain.store(ACCOUNT, 'x') is False
    assert keychain.delete(ACCOUNT) is False
    assert capsys.readouterr().out.count('the password is asked instead') == 3


def test_no_store_offers_nothing_and_fails_nothing(monkeypatch):
    monkeypatch.setattr(keychain, '_store', lambda platform=None: None)
    assert not keychain.available() and keychain.get(ACCOUNT) is None and keychain.store(ACCOUNT, 'x') is False


def test_linux_without_secret_tool_has_no_store(monkeypatch, capsys):
    monkeypatch.undo()  # the real _store, on a pretend Linux without secret-tool
    monkeypatch.setattr(keychain, '_backend_tried', False)
    monkeypatch.setattr(keychain, '_backend', None)
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    assert keychain._store('linux') is None
    assert 'libsecret-tools' in capsys.readouterr().out


def real_store():
    if sys.platform == 'win32':
        return keychain._WindowsCredentials()
    if sys.platform == 'darwin' and os.environ.get('TM1_KEYCHAIN_TEST') == '1':
        return keychain._MacKeychain()
    if sys.platform.startswith('linux') and shutil.which('secret-tool') and os.environ.get('TM1_KEYCHAIN_TEST') == '1':
        return keychain._SecretTool()
    pytest.skip('the real store: Windows always, macOS and Linux with TM1_KEYCHAIN_TEST=1')


def test_the_real_store_round_trips_and_deletes(monkeypatch):
    store = real_store()
    monkeypatch.setattr(keychain, 'SERVICE', 'Sublime Text TM1 (test)')
    try:
        assert store.get(ACCOUNT) is None
        store.store(ACCOUNT, 'pässwörd')
        assert store.get(ACCOUNT) == 'pässwörd'
        store.store(ACCOUNT, 'second')
        assert store.get(ACCOUNT) == 'second'
    finally:
        store.delete(ACCOUNT)
    assert store.get(ACCOUNT) is None
    store.delete(ACCOUNT)  # nothing stored: not an error
