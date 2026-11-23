"""plugin.gateway: requests off the UI thread, results back on it, credentials at first use."""

import pytest
import sublime
from skipcheck_tm1.errors import ODataError, Tm1ApiError, Tm1ErrorKind

from fakes import FakeWindow
from tm1pkg.core.connection import Connection
from tm1pkg.plugin import credentials, gateway
from tm1pkg.plugin.gateway import Gateway

PROJECT = '/p/sales.sublime-project'
CONNECTION = Connection(address='tm1', port='8010', user='admin')


def refused(kind=Tm1ErrorKind.CREDENTIAL_REJECTED):
    return Tm1ApiError.of_kind(401, kind, ODataError(message='refused'), 'GET', 'http://tm1:8010/api/v1/x')


class FakeClient:
    def __init__(self, password):
        self.password, self.closed = password, False

    def close(self):
        self.closed = True


class Harness:
    """A gateway whose work runs at once, whose UI callbacks are queued (as the UI thread would
    run them later), and whose clients are FakeClients."""

    def __init__(self):
        self.window = FakeWindow()
        self.clients = []
        self.ui = []
        self.gateway = Gateway(PROJECT, CONNECTION, connect=self.connect,
                               submit=lambda fn, *args: fn(*args), on_ui=self.ui.append)

    def connect(self, connection, password):
        client = FakeClient(password)
        self.clients.append(client)
        return client

    def answer(self, password):
        panel = self.window.panels[-1]
        panel.type(password)
        panel.submit()

    def run_ui(self):
        while self.ui:
            self.ui.pop(0)()


@pytest.fixture(autouse=True)
def clean():
    credentials.forget_all()
    sublime.dialogs.clear()
    yield
    credentials.forget_all()


@pytest.fixture
def h():
    return Harness()


def test_asks_for_the_password_then_runs_the_work_and_reports_on_the_ui_thread(h):
    done = []
    h.gateway.run(h.window, lambda client: client.password.upper(), done.append)
    assert done == [] and len(h.window.panels) == 1
    h.answer('apple')
    assert done == []  # not until the UI thread runs it
    h.run_ui()
    assert done == ['APPLE']


def test_reuses_the_client_while_the_password_holds(h):
    seen = []
    h.gateway.run(h.window, seen.append)
    h.answer('apple')
    h.gateway.run(h.window, seen.append)
    assert seen[0] is seen[1] and len(h.clients) == 1 and len(h.window.panels) == 1


def test_a_refused_password_is_forgotten_and_asked_once_more(h):
    attempts, done = [], []

    def work(client):
        attempts.append(client.password)
        if client.password == 'wrong':
            raise refused()
        return 'ok'

    h.gateway.run(h.window, work, done.append)
    h.answer('wrong')
    assert h.clients[0].closed
    h.run_ui()
    assert len(h.window.panels) == 2
    h.answer('apple')
    h.run_ui()
    assert attempts == ['wrong', 'apple'] and done == ['ok']


def test_a_second_refusal_is_reported_not_asked_again(h):
    errors = []

    def work(client):
        raise refused()

    h.gateway.run(h.window, work, on_error=errors.append)
    h.answer('wrong')
    h.run_ui()
    h.answer('still wrong')
    h.run_ui()
    assert len(h.window.panels) == 2 and len(errors) == 1
    assert errors[0].kind == Tm1ErrorKind.CREDENTIAL_REJECTED


def test_other_authentication_errors_are_not_retried(h):
    errors = []
    h.gateway.run(h.window, lambda c: (_ for _ in ()).throw(refused(Tm1ErrorKind.UNAUTHENTICATED)),
                  on_error=errors.append)
    h.answer('apple')
    h.run_ui()
    assert len(h.window.panels) == 1 and len(errors) == 1


def test_an_unhandled_error_is_shown_not_lost(h, capsys):
    def work(client):
        raise RuntimeError('TM1 is down')

    h.gateway.run(h.window, work)
    h.answer('apple')
    h.run_ui()
    assert len(sublime.dialogs) == 1
    assert 'TM1 is down' in sublime.dialogs[0] and 'admin at http://tm1:8010/api/v1/' in sublime.dialogs[0]
    assert 'Traceback' in capsys.readouterr().out


def test_an_untrusted_certificate_says_how_to_fix_it():
    import httpx2

    from tm1pkg.core.connection import build_client

    def handler(request):
        raise httpx2.ConnectError('[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed '
                                 'certificate', request=request)

    secure = Connection(address='tm1', port='8010', user='admin', ssl=True)
    client = build_client(secure, 'apple', http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    with pytest.raises(Exception) as raised:
        client.processes.list(select='Name')
    client.close()
    assert '"verify"' in gateway.describe_error(secure, raised.value)
    assert '"verify"' not in gateway.describe_error(secure, RuntimeError('TM1 is down'))


def test_a_window_without_a_project_or_connection_says_so():
    assert gateway.for_window(FakeWindow()) is None
    assert gateway.for_window(FakeWindow(project={'settings': {}}, project_file=PROJECT)) is None
    assert len(sublime.dialogs) == 2 and 'Create New TM1 Project' in sublime.dialogs[1]


def test_a_project_gets_one_gateway_until_its_connection_changes():
    settings = {'settings': {'tm1': {'address': 'tm1', 'port': '8010', 'user': 'admin'}}}
    window = FakeWindow(project=settings, project_file=PROJECT)
    first = gateway.for_window(window)
    assert gateway.for_window(window) is first
    settings['settings']['tm1']['port'] = '8011'
    assert gateway.for_window(window) is not first
    gateway.shutdown()
