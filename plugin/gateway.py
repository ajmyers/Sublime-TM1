"""The gateway to TM1: one per project, through which every command reaches the server.

- Requests run on the package's own threads, never Sublime's UI thread (a slow TM1 freezes
  nothing) and not on Sublime's shared async thread either (a five-minute process run would hold up
  every other package's async work).
- Results and errors come back on the UI thread. An error nobody handles is shown in a dialog and
  printed to the console with its traceback; it's never lost in a thread.
- The password is asked at first use, or read from the credential store when the user chose to
  remember it (credentials.py). When TM1 refuses it, it's forgotten (and removed from the store) and
  asked for once more.
"""

import dataclasses
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

import sublime

from ..core.connection import NotConfigured, build_client, default_method, from_project_settings
from . import browser_sign_in, credentials

WORKERS = 4

_executor = None
_gateways = {}
_lock = threading.Lock()


def _submit(fn, *args):
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix='tm1')
        executor = _executor
    return executor.submit(fn, *args)


def in_background(work, on_done, on_error):
    """Runs ``work()`` on the gateway's threads and hands its result or error back on the UI thread:
    for work that's no project's yet, like the probes of setting one up."""
    def run():
        try:
            result = work()
        except Exception as e:
            # Bound now: the name e is gone once this except block ends, before the UI thread runs it
            sublime.set_timeout(lambda error=e: on_error(error), 0)
        else:
            sublime.set_timeout(lambda: on_done(result), 0)
    _submit(run)


def shutdown():
    """Closes every session and stops the threads: for plugin_unloaded."""
    global _executor
    with _lock:
        gateways, executor = list(_gateways.values()), _executor
        _gateways.clear()
        _executor = None
    for gateway in gateways:
        gateway.close()
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
    credentials.forget_all()
    browser_sign_in.forget_all()


def for_window(window, quiet=False):
    """The gateway for the window's project, or None (having said why, unless quiet) when the window
    has no project or the project no TM1 connection."""
    project = window.project_file_name()
    if not project:
        if not quiet:
            sublime.error_message('TM1: this window has no project. Open a TM1 project, or run '
                                  '"TM1: Config - Create New TM1 Project".')
        return None
    try:
        connection = from_project_settings((window.project_data() or {}).get('settings'))
    except NotConfigured as e:
        if not quiet:
            sublime.error_message('TM1: ' + str(e))
        return None
    with _lock:
        gateway = _gateways.get(project)
        if gateway is not None and gateway.connection != connection:
            # The project's connection changed: start again with the new one
            gateway.close()
            credentials.forget(project)
            browser_sign_in.forget(project)
            gateway = None
        if gateway is None:
            gateway = _gateways[project] = Gateway(project, connection)
    return gateway


def _resolve(connection):
    """The method from TM1 and Cognos; what 0.2.x did for a project from 0.2.x, or when they can't
    be asked."""
    from ..core.discovery import DiscoveryError, Method, resolve_method

    if connection.legacy and not connection.auth:
        return Method(default_method(connection), connection.dispatcher)
    try:
        return resolve_method(connection)
    except (DiscoveryError, OSError, ValueError) as e:
        print('TM1: couldn\'t work out how to log in to {} ({}); logging in as 0.2.x did'.format(
            connection.base_url, e))
        return Method(default_method(connection), connection.dispatcher)
    except Exception as e:  # an HTTP error from the probe
        print('TM1: couldn\'t work out how to log in to {} ({}); logging in as 0.2.x did'.format(
            connection.base_url, e))
        return Method(default_method(connection), connection.dispatcher)


def _find(error, kind):
    """The error, or one it was raised from, of the given kind."""
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, kind):
            return error
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return None


def _save_auth(window, auth):
    """Remembers the method in the project's "tm1" settings, so the browser isn't tried again.
    Whether it did: a project with only 0.2.x's settings isn't given new ones."""
    project = window.project_data() or {}
    settings = project.setdefault('settings', {})
    if isinstance(settings.get('tm1'), dict):
        settings['tm1']['auth'] = auth
        window.set_project_data(project)
        return True
    return False


def describe_error(connection, error):
    from skipcheck_tm1.errors import Tm1TransportError

    message = str(error) or type(error).__name__
    untrusted = 'CERTIFICATE_VERIFY_FAILED' in message + str(error.__cause__ or '')
    if isinstance(error, Tm1TransportError) and untrusted:
        message += ('\n\nTM1\'s certificate isn\'t trusted. If it\'s self-signed, set "verify" under "tm1" '
                    'in the project\'s settings to the path of a CA bundle that signs it, or to false to '
                    'not check it.')
    return 'TM1 ({}):\n\n{}'.format(connection.describe(), message)


class Gateway:
    def __init__(self, key, connection, connect=build_client, submit=None, on_ui=None, resolve=None,
                 passport_source=browser_sign_in.passport_source):
        self.key = key
        self.connection = connection
        self._connect = connect
        self._submit = submit or _submit
        self._on_ui = on_ui or (lambda fn: sublime.set_timeout(fn, 0))
        self._resolve = resolve or _resolve
        self._passport_source = passport_source
        self.method = None
        self._client = None
        self._client_password = None
        self._lock = threading.Lock()

    def run(self, window, work, on_done=None, on_error=None, on_cancel=None):
        """Runs ``work(client)`` off the UI thread, then ``on_done(result)`` or
        ``on_error(error)`` on it. Asks for the password first if it isn't known yet.
        ``on_cancel()`` runs on the UI thread if the user cancels signing in instead (Esc at a
        prompt, the browser window closed), when neither of the others will."""
        self._run(window, work, on_done, on_error, retry=True, on_cancel=on_cancel)

    def _run(self, window, work, on_done, on_error, retry, on_cancel=None):
        if self.method is None:
            # How to log in is worked out once, off the UI thread: it asks TM1 and Cognos
            self._submit(self._find_method, window, work, on_done, on_error, retry, on_cancel)
            return

        def start(password):
            self._submit(self._work, window, work, password, on_done, on_error, retry, on_cancel)

        if self.method.kind == 'browser':
            start(None)
        else:
            credentials.with_password(window, self.key, self.connection, start, on_cancel)

    def _find_method(self, window, work, on_done, on_error, retry, on_cancel=None):
        self.method = self._resolve(self.connection)
        self._on_ui(lambda: self._run(window, work, on_done, on_error, retry, on_cancel))

    def _work(self, window, work, password, on_done, on_error, retry, on_cancel=None):
        try:
            result = work(self._client_for(password, window))
        except Exception as e:
            self._failed(e, window, work, on_done, on_error, retry, on_cancel)
            return
        if password is not None:
            self._on_ui(lambda: credentials.accepted(window, self.key, self.connection))
        if on_done is not None:
            self._on_ui(lambda: on_done(result))

    def _failed(self, error, window, work, on_done, on_error, retry, on_cancel=None):
        from skipcheck_tm1.errors import Tm1AuthenticationError, Tm1ErrorKind

        from ..core.browser import BrowserError, SignInCancelled

        browser_error = _find(error, BrowserError)
        if isinstance(browser_error, SignInCancelled):
            self._drop_client()

            def cancelled():
                window.status_message('TM1: sign-in cancelled')
                if on_cancel is not None:
                    on_cancel()
            self._on_ui(cancelled)
        elif browser_error is not None:
            self._drop_client()
            self._on_ui(lambda: self._browser_failed(window, browser_error, work, on_done, on_error, on_cancel))
        elif isinstance(error, Tm1AuthenticationError) and error.kind == Tm1ErrorKind.CREDENTIAL_REJECTED:
            # A wrong password, or a passport TM1 no longer takes: forgotten (in the credential store
            # too), and asked once more
            credentials.rejected(self.key, self.connection)
            browser_sign_in.forget(self.key)
            self._drop_client()
            if retry:
                self._on_ui(lambda: self._run(window, work, on_done, on_error, retry=False, on_cancel=on_cancel))
            else:
                self._fail(error, on_error)
        else:
            self._fail(error, on_error)

    def _browser_failed(self, window, error, work, on_done, on_error, on_cancel=None):
        """The browser sign-in didn't work: say why, and offer the other ways in."""
        from ..core.discovery import Method

        choices = [
            ('Sign in with a user and password', 'For a namespace Cognos also lets log on with a password'),
            ('Paste a CAM passport', 'From a browser where you are signed in to Cognos: its cam_passport cookie'),
            ('Try the browser again', str(error)),
            ('Cancel', ''),
        ]

        def chosen(index):
            if index == 0:
                self.method = Method('cam', self.method.dispatcher if self.method else '')
                if _save_auth(window, 'cam'):
                    # Matching the project's settings again, so the next command keeps this gateway,
                    # and the password and session that come with it
                    self.connection = dataclasses.replace(self.connection, auth='cam')
                self._run(window, work, on_done, on_error, retry=True, on_cancel=on_cancel)
            elif index == 1:
                def pasted(value):
                    browser_sign_in._passports[self.key] = value.strip()
                    self._run(window, work, on_done, on_error, retry=False, on_cancel=on_cancel)
                credentials.ask_secret(window, 'CAM passport:', pasted, on_cancel)
            elif index == 2:
                browser_sign_in.forget(self.key)
                self._run(window, work, on_done, on_error, retry=True, on_cancel=on_cancel)
            elif on_cancel is not None:
                # Cancel, or Esc (-1)
                on_cancel()

        items = [sublime.QuickPanelItem(trigger, details=details) for trigger, details in choices]
        window.show_quick_panel(items, chosen, placeholder='TM1 browser sign-in failed: ' + str(error))

    def _fail(self, error, on_error):
        trace = traceback.format_exc()
        if on_error is not None:
            self._on_ui(lambda: on_error(error))
            return

        def show():
            print(trace)
            sublime.error_message(describe_error(self.connection, error))

        self._on_ui(show)

    def _client_for(self, password, window=None):
        with self._lock:
            if self._client is None or self._client_password != password:
                if self._client is not None:
                    self._client.close()
                if self.method is not None and self.method.kind == 'browser':
                    passport = self._passport_source(self.key, self.method.dispatcher, self.connection.namespace,
                                                     on_window=lambda: self._waiting_for_browser(window))
                    self._client = self._connect(self.connection, None, method='browser', passport=passport)
                else:
                    method = self.method.kind if self.method is not None else None
                    self._client = self._connect(self.connection, password, method=method)
                self._client_password = password
            return self._client

    def _waiting_for_browser(self, window):
        def show():
            if window is not None:
                window.status_message('TM1: sign in in the browser window to connect to {}'.format(
                    self.connection.base_url))
        self._on_ui(show)

    def _drop_client(self):
        with self._lock:
            client, self._client, self._client_password = self._client, None, None
        if client is not None:
            client.close()

    def close(self):
        self._drop_client()
