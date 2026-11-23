"""plugin.gateway: requests off the UI thread, results back on it, credentials at first use."""

import pytest
import sublime
from skipcheck_tm1.errors import ODataError, Tm1ApiError, Tm1ErrorKind

from fakes import FakeWindow
from tm1pkg.core.connection import Connection
from tm1pkg.core.discovery import Method
from tm1pkg.plugin import browser_sign_in, credentials, gateway
from tm1pkg.plugin.gateway import Gateway

PROJECT = '/p/sales.sublime-project'
CONNECTION = Connection(address='tm1', port='8010', user='admin')


def refused(kind=Tm1ErrorKind.CREDENTIAL_REJECTED):
    return Tm1ApiError.of_kind(401, kind, ODataError(message='refused'), 'GET', 'http://tm1:8010/api/v1/x')


class FakeClient:
    def __init__(self, password, method=None, passport=None):
        self.password, self.method, self.passport, self.closed = password, method, passport, False

    def close(self):
        self.closed = True


class Harness:
    """A gateway whose work runs at once, whose UI callbacks are queued (as the UI thread would
    run them later), and whose clients are FakeClients."""

    def __init__(self, method=Method('basic'), connection=CONNECTION):
        self.window = FakeWindow()
        self.clients = []
        self.ui = []
        self.resolved = []
        self.passports = ['passport-1', 'passport-2']
        self.browser_opened = 0

        def resolve(c):
            self.resolved.append(c)
            return method

        def passports(key, dispatcher, namespace, on_window=None):
            def passport():
                if key not in browser_sign_in._passports:
                    self.browser_opened += 1
                    on_window()
                    browser_sign_in._passports[key] = self.passports.pop(0)
                return browser_sign_in._passports[key]
            return passport

        self.gateway = Gateway(PROJECT, connection, connect=self.connect, submit=lambda fn, *args: fn(*args),
                               on_ui=self.ui.append, resolve=resolve, passport_source=passports)

    def connect(self, connection, password, method=None, passport=None):
        client = FakeClient(password, method, passport)
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
    browser_sign_in.forget_all()
    sublime.dialogs.clear()
    yield
    credentials.forget_all()
    browser_sign_in.forget_all()


@pytest.fixture
def h():
    return Harness()


def test_asks_for_the_password_then_runs_the_work_and_reports_on_the_ui_thread(h):
    done = []
    h.gateway.run(h.window, lambda client: client.password.upper(), done.append)
    h.run_ui()  # working out how to log in comes back to the UI thread first
    assert done == [] and len(h.window.panels) == 1
    h.answer('apple')
    assert done == []  # not until the UI thread runs it
    h.run_ui()
    assert done == ['APPLE']


def test_reuses_the_client_while_the_password_holds(h):
    seen = []
    h.gateway.run(h.window, seen.append)
    h.run_ui()
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
    h.run_ui()
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
    h.run_ui()
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
    h.run_ui()
    h.answer('apple')
    h.run_ui()
    assert len(h.window.panels) == 1 and len(errors) == 1


def test_an_unhandled_error_is_shown_not_lost(h, capsys):
    def work(client):
        raise RuntimeError('TM1 is down')

    h.gateway.run(h.window, work)
    h.run_ui()
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


# Working out how to log in, and the browser sign-in

CAM = Connection(address='tm1', port='8010', user='', namespace='OIDC')


def test_works_out_how_to_log_in_once_per_session(h):
    h.gateway.run(h.window, lambda c: None)
    h.run_ui()
    h.answer('apple')
    h.gateway.run(h.window, lambda c: None)
    h.run_ui()
    assert len(h.resolved) == 1


def test_a_namespace_that_signs_in_in_the_browser_asks_for_no_password():
    h = Harness(method=Method('browser', 'http://cognos:9300/bi/v1/disp'), connection=CAM)
    done = []
    h.gateway.run(h.window, lambda client: (client.method, client.passport()), done.append)
    h.run_ui()
    h.run_ui()
    assert h.window.panels == []
    assert done == [('browser', 'passport-1')]
    assert h.window.statuses and 'browser window' in h.window.statuses[-1]


def test_the_passport_is_reused_until_tm1_refuses_it_then_fetched_again():
    h = Harness(method=Method('browser', 'http://cognos:9300/bi/v1/disp'), connection=CAM)
    seen = []

    def work(client):
        passport = client.passport()
        seen.append(passport)
        if passport == 'passport-1' and len(seen) == 2:
            raise refused()
        return passport

    for _ in range(2):
        h.gateway.run(h.window, work)
        h.run_ui()
        h.run_ui()
    assert seen == ['passport-1', 'passport-1', 'passport-2'] and h.browser_opened == 2


def test_a_password_namespace_asks_for_the_password_as_0_2_did():
    h = Harness(method=Method('cam', 'http://cognos:9300/bi/v1/disp'), connection=CAM)
    h.gateway.run(h.window, lambda client: client.method)
    h.run_ui()
    assert len(h.window.panels) == 1


def test_when_cognos_cant_be_asked_it_logs_in_as_0_2_did(monkeypatch, capsys):
    from tm1pkg.core import discovery

    def unreachable(connection, client=None):
        raise discovery.DiscoveryError('no Cognos here')

    monkeypatch.setattr(discovery, 'resolve_method', unreachable)
    assert gateway._resolve(CAM) == Method('cam', '')
    assert gateway._resolve(CONNECTION) == Method('basic', '')
    assert 'logging in as 0.2.x did' in capsys.readouterr().out


# When the browser can't be used

def failing_browser(error):
    h = Harness(method=Method('browser', 'http://cognos:9300/bi/v1/disp'), connection=CAM_PROJECT)

    def passports(key, dispatcher, namespace, on_window=None):
        def passport():
            if key in browser_sign_in._passports:
                return browser_sign_in._passports[key]
            raise RuntimeError('the authenticator failed') from error
        return passport

    h.gateway._passport_source = passports
    return h


CAM_PROJECT = Connection(address='tm1', port='8010', user='alice', namespace='OIDC')


def run(h, work=lambda client: client.passport() if client.method == 'browser' else client.password):
    done = []
    h.gateway.run(h.window, work, done.append)
    h.run_ui()
    h.run_ui()
    return done


def test_a_project_from_0_2_logs_in_as_0_2_did_without_asking_tm1_or_cognos(monkeypatch):
    from tm1pkg.core import discovery

    monkeypatch.setattr(discovery, 'resolve_method', lambda c, client=None: pytest.fail('probed'))
    legacy = Connection(address='tm1', port='8010', user='alice', namespace='OIDC', legacy=True)
    assert gateway._resolve(legacy) == Method('cam', '')


def test_a_browser_that_fails_offers_the_other_ways_in_and_says_why():
    from tm1pkg.core.browser import DebuggingBlocked

    h = failing_browser(DebuggingBlocked('blocked by policy'))
    assert run(h) == []
    menu = h.window.quick_panels[0]
    assert [i.trigger for i in menu['items']] == ['Sign in with a user and password', 'Paste a CAM passport',
                                                   'Try the browser again', 'Cancel']
    assert 'blocked by policy' in menu['placeholder']
    assert sublime.dialogs == []


def test_choosing_a_password_saves_it_as_the_projects_method_and_asks_for_it():
    from tm1pkg.core.browser import BrowserError

    h = failing_browser(BrowserError('no browser'))
    h.window.project = {'settings': {'tm1': {'address': 'tm1', 'port': '8010', 'namespace': 'OIDC'}}}
    run(h)
    h.window.quick_panels[0]['on_select'](0)
    assert h.window.project['settings']['tm1']['auth'] == 'cam'
    h.answer('secret')
    h.run_ui()
    assert h.clients[-1].method == 'cam' and h.clients[-1].password == 'secret'


def test_a_pasted_passport_is_used():
    from tm1pkg.core.browser import BrowserError

    h = failing_browser(BrowserError('no browser'))
    run(h)
    h.window.quick_panels[0]['on_select'](1)
    # The pasted passport goes into the store the browser fills, and the work runs with it
    h.window.panels[-1].type('MTsxMDE6pasted')
    h.window.panels[-1].submit()
    h.run_ui()
    assert browser_sign_in._passports[PROJECT] == 'MTsxMDE6pasted'
    assert h.clients[-1].passport() == 'MTsxMDE6pasted'


def test_closing_the_window_is_a_quiet_cancel():
    from tm1pkg.core.browser import SignInCancelled

    h = failing_browser(SignInCancelled('closed'))
    run(h)
    assert h.window.quick_panels == [] and sublime.dialogs == []
    assert h.window.statuses[-1] == 'TM1: sign-in cancelled'
