"""plugin.browser_sign_in: the passport from the browser, kept in memory."""

import pytest
import sublime

from tm1pkg.core import browser
from tm1pkg.plugin import browser_sign_in


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(sublime, '_cache_path', str(tmp_path))
    browser_sign_in.forget_all()
    yield
    browser_sign_in.forget_all()


def test_signs_in_once_and_reuses_the_passport_until_forgotten():
    calls = []

    def read_cookie(executable, profile, url, on_window=None):
        calls.append((executable, profile, url))
        return 'passport-{}'.format(len(calls))

    source = browser_sign_in.passport_source('/p/x.sublime-project', 'http://cognos:9300/bi/v1/disp', 'OIDC',
                                             read_cookie=read_cookie, executable=lambda: '/b/chrome')
    assert source() == source() == 'passport-1'
    assert calls[0][2] == 'http://cognos:9300/bi/?CAMNamespace=OIDC'
    assert calls[0][1].endswith('browser-profile') and calls[0][1].startswith(sublime.cache_path())
    browser_sign_in.forget('/p/x.sublime-project')
    assert source() == 'passport-2'


def test_without_a_browser_it_says_how_to_set_one(monkeypatch):
    monkeypatch.setattr(browser, 'find_browser', lambda setting=None: None)
    with pytest.raises(browser.BrowserError, match='"browser"'):
        browser_sign_in.browser_executable()
