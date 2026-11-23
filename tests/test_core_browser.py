"""core.browser: finding a browser on each platform, and reading a cookie from it.

The tests that start a browser run wherever one is installed, as on GitHub's Windows, macOS and
Linux runners; elsewhere they're skipped.
"""

import http.server
import os
import threading
import time

import pytest

from tm1pkg.core import browser
from tm1pkg.core.browser import Browser, SignInCancelled, find_browser, read_cookie

# Finding one


def test_windows_prefers_the_registered_app_paths():
    registered = {'chrome.exe': r'D:\Apps\Chrome\chrome.exe'}
    path = find_browser(platform='win32', env={}, exists=lambda p: p == registered['chrome.exe'],
                        app_path=registered.get)
    assert path == r'D:\Apps\Chrome\chrome.exe'


def test_windows_finds_edge_where_windows_puts_it():
    edge = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
    path = find_browser(platform='win32', env={'ProgramFiles(x86)': r'C:\Program Files (x86)'},
                        exists=lambda p: p == edge, app_path=lambda name: None)
    assert path == edge


def test_macos_looks_in_applications_and_the_users_own():
    chrome = '/Users/me/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    assert find_browser(platform='darwin', exists=lambda p: p == chrome, home='/Users/me') == chrome
    edge = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
    assert find_browser(platform='darwin', exists=lambda p: p == edge, home='/Users/me') == edge


def test_linux_looks_on_the_path():
    on_path = {'chromium': '/usr/bin/chromium'}
    assert find_browser(platform='linux', which=on_path.get) == '/usr/bin/chromium'
    assert find_browser(platform='linux', which=lambda name: None) is None


def test_the_users_setting_wins():
    assert find_browser(setting='/opt/b/browser', exists=lambda p: p == '/opt/b/browser') == '/opt/b/browser'
    assert find_browser(setting='my-chrome', exists=lambda p: False, which={'my-chrome': '/u/my-chrome'}.get) \
        == '/u/my-chrome'


# Using one


def processes_using(profile):
    """The browser processes still running with this profile, where that can be asked."""
    import subprocess

    if os.name != 'posix':
        return []
    time.sleep(0.5)
    listing = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True).stdout
    return [line for line in listing.splitlines() if str(profile) in line]

EXECUTABLE = find_browser()
needs_browser = pytest.mark.skipif(EXECUTABLE is None, reason='no Chromium-based browser installed')
TRANSPORTS = ['port'] + (['pipe'] if os.name == 'posix' else [])


class LoginServer:
    """Sets cam_passport (HttpOnly, as Cognos does) after a 'sign-in' redirect, and a decoy cookie."""

    def __init__(self, delay=0.0):
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith('/bi/'):
                    self.send_response(302)
                    self.send_header('Location', '/signed-in')
                    self.send_header('Set-Cookie', 'other=decoy; Path=/')
                    self.end_headers()
                    return
                time.sleep(server.delay)
                self.send_response(200)
                self.send_header('Set-Cookie', 'cam_passport=MTsxMDE6passport; Path=/; HttpOnly')
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<p>Signed in</p>')

            def log_message(self, *args):
                pass

        self.delay = delay
        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = 'http://127.0.0.1:{}/bi/'.format(self.httpd.server_port)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()


@pytest.fixture
def server():
    s = LoginServer()
    yield s
    s.stop()


@needs_browser
@pytest.mark.parametrize('transport', TRANSPORTS)
def test_reads_an_httponly_cookie_from_a_hidden_window_and_closes_the_browser(server, tmp_path, transport):
    seen = []
    original = Browser.__init__

    def keep(self, *args, **kwargs):
        original(self, *args, **kwargs)
        seen.append(self)

    browser_init = pytest.MonkeyPatch()
    browser_init.setattr(Browser, '__init__', keep)
    try:
        value = read_cookie(EXECUTABLE, str(tmp_path / 'profile'), server.url, transport=transport)
    finally:
        browser_init.undo()
    assert value == 'MTsxMDE6passport'
    assert len(seen) == 1 and not seen[0].running()
    assert not processes_using(tmp_path / 'profile')


@needs_browser
@pytest.mark.parametrize('transport', TRANSPORTS)
def test_reads_only_the_cookie_asked_for_on_the_host_asked_for(server, tmp_path, transport):
    b = Browser(EXECUTABLE, str(tmp_path / 'profile'), server.url, hidden=True, transport=transport)
    try:
        assert browser.wait_for_cookie(b, 'cam_passport', '127.0.0.1', 15) == 'MTsxMDE6passport'
        assert b.cookie('cam_passport', 'cognos.example.com') is None
        assert b.cookie('missing', '127.0.0.1') is None
    finally:
        b.close()


@needs_browser
@pytest.mark.parametrize('transport', TRANSPORTS)
def test_a_window_closed_before_signing_in_is_a_cancel(tmp_path, transport):
    slow = LoginServer(delay=30)
    b = Browser(EXECUTABLE, str(tmp_path / 'profile'), slow.url, hidden=True, transport=transport)
    try:
        # Only the main process, as a crash would: its helpers must not outlive close()
        threading.Timer(1.0, lambda: os.kill(b._pid, 9)).start()
        with pytest.raises(SignInCancelled):
            browser.wait_for_cookie(b, 'cam_passport', '127.0.0.1', 20)
    finally:
        b.close()
        slow.stop()
    assert not processes_using(tmp_path / 'profile')


@needs_browser
@pytest.mark.skipif(os.name != 'posix', reason='permissions are POSIX')
def test_the_profile_is_private(server, tmp_path):
    profile = tmp_path / 'profile'
    read_cookie(EXECUTABLE, str(profile), server.url, transport='pipe')
    assert (profile.stat().st_mode & 0o777) == 0o700


@needs_browser
@pytest.mark.skipif(os.name != 'posix', reason='the pipe transport is POSIX')
def test_the_pipe_works_from_a_fresh_process(server, tmp_path):
    # A fresh process's pipes land on descriptors 3 and 4, where the browser expects its own:
    # the case pytest, with many files open, never hits
    import subprocess
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = (
        'import sys, types; sys.path.insert(0, {root!r});'
        'p = types.ModuleType("tm1pkg"); p.__path__ = [{root!r}]; sys.modules["tm1pkg"] = p;'
        'from tm1pkg.core.browser import read_cookie;'
        'print(read_cookie({exe!r}, {profile!r}, {url!r}, transport="pipe"))'
    ).format(root=root, exe=EXECUTABLE, profile=str(tmp_path / 'profile'), url=server.url)
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=60)
    assert result.stdout.strip() == 'MTsxMDE6passport', result.stderr[-2000:]
