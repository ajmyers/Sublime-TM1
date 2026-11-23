"""Setting up a project from the host alone, updating one, and signing out."""

import json
import os

import pytest
import sublime

from fakes import FakeWindow
from tm1pkg.core import discovery
from tm1pkg.plugin import browser_sign_in, credentials, gateway, setup


@pytest.fixture(autouse=True)
def synchronous(monkeypatch):
    def in_background(work, on_done, on_error):
        try:
            result = work()
        except Exception as e:
            on_error(e)
        else:
            on_done(result)
    monkeypatch.setattr(gateway, 'in_background', in_background)
    sublime.dialogs.clear()
    sublime._ok_cancel_answers.clear()


def fake_servers(monkeypatch, servers=(), scheme=discovery.Scheme(ssl=False), challenge=discovery.Challenge('basic'),
                 namespaces=None, kinds=None, cognos_down=()):
    asked = {'admin': 0}

    def admin(host):
        asked['admin'] += 1
        return list(servers)

    def namespace_list(dispatcher, verify=True):
        if dispatcher in cognos_down:
            raise discovery.DiscoveryError('unreachable')
        return namespaces

    monkeypatch.setattr(discovery, 'admin_servers', admin)
    monkeypatch.setattr(discovery, 'probe_scheme', lambda host, port: scheme)
    monkeypatch.setattr(discovery, 'challenge', lambda url, verify=True: challenge)
    monkeypatch.setattr(discovery, 'namespaces', namespace_list)
    monkeypatch.setattr(discovery, 'login_kind', lambda d, ns, verify=True: kinds[ns])
    return asked


def answer(window, text):
    panel = window.panels[-1]
    panel.text = ''
    panel.type(text)
    panel.submit()


def run_setup(window, initial=''):
    got = []
    setup.Setup(window, got.append, initial).start()
    return got


def test_basic_security_from_the_admin_servers_list(monkeypatch):
    asked = fake_servers(monkeypatch, servers=[discovery.Server('Planning', 8010, False),
                                               discovery.Server('SData', 8011, False)])
    window = FakeWindow()
    got = run_setup(window)
    answer(window, 'tm1.example.com')
    window.quick_panels[0]['on_select'](1)
    assert window.panels[-1].caption == 'TM1 user:'
    answer(window, 'admin')
    assert asked['admin'] == 1
    assert got == [{'address': 'tm1.example.com', 'port': '8011', 'ssl': False, 'verify': True, 'user': 'admin',
                    'namespace': '', 'async_requests': True, 'auth': 'basic'}]


def test_a_url_with_a_port_skips_the_admin_server(monkeypatch):
    asked = fake_servers(monkeypatch, scheme=discovery.Scheme(ssl=True))
    window = FakeWindow()
    got = run_setup(window)
    answer(window, 'https://tm1:8010/')
    answer(window, 'admin')
    assert asked['admin'] == 0 and got[0]['ssl'] is True and got[0]['port'] == '8010'


def test_no_admin_server_asks_for_the_port(monkeypatch):
    fake_servers(monkeypatch)
    window = FakeWindow()
    got = run_setup(window)
    answer(window, 'tm1')
    assert 'TM1 REST API port' in window.panels[-1].caption
    answer(window, '8012')
    answer(window, 'admin')
    assert got[0]['port'] == '8012'


def test_an_untrusted_certificate_is_asked_about(monkeypatch):
    fake_servers(monkeypatch, scheme=discovery.Scheme(ssl=True, trusted=False))
    window = FakeWindow()
    got = run_setup(window)
    answer(window, 'tm1:8010')
    assert "certificate isn't trusted" in sublime.dialogs[-1]
    answer(window, 'admin')
    assert got[0]['verify'] is False and got[0]['ssl'] is True
    sublime._ok_cancel_answers.append(False)
    window2 = FakeWindow()
    got2 = run_setup(window2)
    answer(window2, 'tm1:8010')
    assert got2 == [] and window2.panels[-1].caption.startswith('TM1 server')


def test_a_browser_namespace_asks_nothing_more(monkeypatch):
    fake_servers(monkeypatch, challenge=discovery.Challenge('cam', 'http://cognos:9300/bi/v1/disp'),
                 namespaces=['OIDC', 'LDAP'], kinds={'OIDC': 'browser', 'LDAP': 'password'})
    window = FakeWindow()
    got = run_setup(window)
    answer(window, 'tm1:8010')
    window.quick_panels[0]['on_select'](0)
    assert got[0]['auth'] == 'browser' and got[0]['namespace'] == 'OIDC' and got[0]['user'] == ''
    assert 'dispatcher' not in got[0]


def test_a_password_namespace_asks_the_user(monkeypatch):
    fake_servers(monkeypatch, challenge=discovery.Challenge('cam', 'http://cognos:9300/bi/v1/disp'),
                 namespaces=['LDAP'], kinds={'LDAP': 'password'})
    window = FakeWindow()
    got = run_setup(window)
    answer(window, 'tm1:8010')
    assert window.panels[-1].caption == 'TM1 user in LDAP:'
    answer(window, 'alice')
    assert (got[0]['auth'], got[0]['user'], got[0]['namespace']) == ('cam', 'alice', 'LDAP')


def test_an_unreachable_cognos_is_asked_for_and_kept_as_the_dispatcher(monkeypatch):
    fake_servers(monkeypatch, challenge=discovery.Challenge('cam', 'http://cognos:9300/bi/v1/disp'),
                 namespaces=['OIDC'], kinds={'OIDC': 'browser'}, cognos_down={'http://cognos:9300/bi/v1/disp'})
    window = FakeWindow()
    got = run_setup(window)
    answer(window, 'tm1:8010')
    assert "Cognos isn't reachable" in window.panels[-1].caption
    answer(window, 'http://localhost:19300/bi/v1/disp')
    assert got[0]['dispatcher'] == 'http://localhost:19300/bi/v1/disp' and got[0]['auth'] == 'browser'


def test_creating_a_project_writes_it_without_a_password_and_opens_it(monkeypatch, tmp_path):
    fake_servers(monkeypatch)
    opened = []
    monkeypatch.setattr(setup, 'open_project', opened.append)
    window = FakeWindow()
    setup.CreateNewTm1Project(window).run()
    answer(window, 'tm1.example.com:8010')
    answer(window, 'admin')
    assert window.panels[-1].caption == 'Project name:' and window.panels[-1].text == 'tm1'
    answer(window, 'Sales')
    answer(window, str(tmp_path / 'Sales'))
    project_file = tmp_path / 'Sales' / 'Sales.sublime-project'
    assert opened == [str(project_file)]
    project = json.loads(project_file.read_text())
    assert project['settings']['tm1']['address'] == 'tm1.example.com' and 'password' not in project_file.read_text()
    assert project['folders'] == [{'name': 'Sales', 'path': str(tmp_path / 'Sales')}]


def test_updating_keeps_0_2_settings_and_offers_to_remove_their_password(monkeypatch):
    fake_servers(monkeypatch)
    legacy = {'address': 'tm1', 'port': '8010', 'user': 'admin', 'ssl': False, 'password': 'kZaQkQ==',
              'namespace': '', 'async_requests_mode': True}
    window = FakeWindow(project={'settings': {'tm1_connection': dict(legacy)}}, project_file='/p/x.sublime-project')
    setup.UpdateTm1Project(window).run()
    assert window.panels[-1].text == 'http://tm1:8010'
    answer(window, 'http://tm1:8010')
    answer(window, 'admin')
    settings = window.project['settings']
    assert settings['tm1']['user'] == 'admin' and settings['tm1_connection']['password'] == 'kZaQkQ=='
    window.quick_panels[-1]['on_select'](0)
    assert 'password' not in window.project['settings']['tm1_connection']
    assert window.project['settings']['tm1_connection']['user'] == 'admin'


def test_signing_out_forgets_the_password_and_passport(tmp_path, monkeypatch):
    monkeypatch.setattr(sublime, '_cache_path', str(tmp_path))
    key = '/p/x.sublime-project'
    credentials._passwords[key] = 'apple'
    browser_sign_in._passports[key] = 'passport'
    os.makedirs(browser_sign_in.profile_folder())
    window = FakeWindow(project={}, project_file=key)
    setup.Tm1SignOutCommand(window).run()
    assert key not in credentials._passwords and key not in browser_sign_in._passports
    window.quick_panels[0]['on_select'](1)
    assert not os.path.exists(browser_sign_in.profile_folder())
