"""The gateway to TM1: one per project, through which every command reaches the server.

- Requests run on the package's own threads, never Sublime's UI thread (a slow TM1 freezes
  nothing) and not on Sublime's shared async thread either (a five-minute process run would hold up
  every other package's async work).
- Results and errors come back on the UI thread. An error nobody handles is shown in a dialog and
  printed to the console with its traceback; it's never lost in a thread.
- The password is asked at first use (credentials.py). When TM1 refuses it, it's forgotten and asked
  for once more.
"""

import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

import sublime

from ..core.connection import NotConfigured, build_client, from_project_settings
from . import credentials

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
            gateway = None
        if gateway is None:
            gateway = _gateways[project] = Gateway(project, connection)
    return gateway


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
    def __init__(self, key, connection, connect=build_client, submit=None, on_ui=None):
        self.key = key
        self.connection = connection
        self._connect = connect
        self._submit = submit or _submit
        self._on_ui = on_ui or (lambda fn: sublime.set_timeout(fn, 0))
        self._client = None
        self._client_password = None
        self._lock = threading.Lock()

    def run(self, window, work, on_done=None, on_error=None):
        """Runs ``work(client)`` off the UI thread, then ``on_done(result)`` or
        ``on_error(error)`` on it. Asks for the password first if it isn't known yet."""
        self._run(window, work, on_done, on_error, retry=True)

    def _run(self, window, work, on_done, on_error, retry):
        def start(password):
            self._submit(self._work, window, work, password, on_done, on_error, retry)

        credentials.with_password(window, self.key, self.connection, start)

    def _work(self, window, work, password, on_done, on_error, retry):
        from skipcheck_tm1.errors import Tm1AuthenticationError, Tm1ErrorKind

        try:
            result = work(self._client_for(password))
        except Tm1AuthenticationError as e:
            if e.kind == Tm1ErrorKind.CREDENTIAL_REJECTED:
                credentials.forget(self.key)
                self._drop_client()
                if retry:
                    self._on_ui(lambda: self._run(window, work, on_done, on_error, retry=False))
                    return
            self._fail(e, on_error)
        except Exception as e:
            self._fail(e, on_error)
        else:
            if on_done is not None:
                self._on_ui(lambda: on_done(result))

    def _fail(self, error, on_error):
        trace = traceback.format_exc()
        if on_error is not None:
            self._on_ui(lambda: on_error(error))
            return

        def show():
            print(trace)
            sublime.error_message(describe_error(self.connection, error))

        self._on_ui(show)

    def _client_for(self, password):
        with self._lock:
            if self._client is None or self._client_password != password:
                if self._client is not None:
                    self._client.close()
                self._client = self._connect(self.connection, password)
                self._client_password = password
            return self._client

    def _drop_client(self):
        with self._lock:
            client, self._client, self._client_password = self._client, None, None
        if client is not None:
            client.close()

    def close(self):
        self._drop_client()
