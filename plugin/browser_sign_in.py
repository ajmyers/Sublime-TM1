"""The CAM passport from a browser sign-in, for namespaces that don't prompt for a password.

The passport is kept in memory per project, given to every TM1 login while TM1 takes it, and
fetched again once TM1 refuses it (the gateway forgets it then). Fetching runs on the gateway's
worker thread: core.browser tries a hidden window first, then opens one the user signs in in.
"""

import os

import sublime

from ..core import browser as browsers
from ..core.discovery import browser_login_url

PACKAGE = 'TM1 Planning Analytics Developer Tools'
SETTINGS = 'TM1 Planning Analytics Developer Tools.sublime-settings'

_passports = {}


def forget(key):
    _passports.pop(key, None)


def forget_all():
    _passports.clear()


def profile_folder():
    """The browser profile the sign-ins use: never the user's own, readable only by them."""
    return os.path.join(sublime.cache_path(), PACKAGE, 'browser-profile')


def browser_executable():
    setting = sublime.load_settings(SETTINGS).get('browser') or None
    executable = browsers.find_browser(setting)
    if executable is None:
        raise browsers.BrowserError(
            'TM1 signs in to this namespace in a browser window, and no Chrome, Edge, Brave or Chromium was '
            'found{}. Install one, or set "browser" in Preferences > Package Settings > TM1 to its path.'.format(
                ' at "{}"'.format(setting) if setting else ''))
    return executable


def passport_source(key, dispatcher, namespace, on_window=None, read_cookie=browsers.read_cookie,
                    executable=browser_executable):
    """The callable skipcheck-tm1's cam_passport takes: the project's passport, signing in for one
    when there's none."""
    def passport():
        if key not in _passports:
            url = browser_login_url(dispatcher, namespace)
            _passports[key] = read_cookie(executable(), profile_folder(), url, on_window=on_window)
        return _passports[key]
    return passport
