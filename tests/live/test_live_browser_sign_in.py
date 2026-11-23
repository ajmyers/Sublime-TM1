"""The browser sign-in against a real Cognos and a TM1 in CAM security. Skipped unless TM1_CAM_URL
names such a TM1, with CAM_NAMESPACE (one that signs in in the browser), CAM_USER and CAM_PASSWORD,
and COGNOS_URL when TM1's ClientCAMURI isn't reachable from here. skipcheck-tm1's pa-setup starts
one (cognos.oidc, cam.namespace oidc), with Keycloak as the provider.

A real browser (hidden) opens Cognos's login for the namespace; the test fills in Keycloak's form
in it, as the user would, and everything else is the real flow.
"""

import os
import time

import pytest

from tm1pkg.core import browser, discovery
from tm1pkg.core.connection import Connection, build_client
from tests_live_url import url_parts

SETTINGS = ['TM1_CAM_URL', 'CAM_NAMESPACE', 'CAM_USER', 'CAM_PASSWORD']
EXECUTABLE = browser.find_browser()
pytestmark = [
    pytest.mark.skipif(not all(os.environ.get(s) for s in SETTINGS),
                       reason='no CAM environment: set ' + ', '.join(SETTINGS)),
    pytest.mark.skipif(EXECUTABLE is None, reason='no Chromium-based browser installed'),
]

FILL_KEYCLOAK = '''(function () {
  var form = document.getElementById('kc-form-login');
  if (!form) return false;
  document.getElementById('username').value = %s;
  document.getElementById('password').value = %s;
  form.submit();
  return true;
})()'''


def connection():
    address, port, ssl = url_parts(os.environ['TM1_CAM_URL'])
    return Connection(address=address, port=port, user='', ssl=ssl, namespace=os.environ['CAM_NAMESPACE'],
                      verify=False, dispatcher=os.environ.get('COGNOS_URL', ''))


def sign_in_as_the_user(url, profile):
    import json

    b = browser.Browser(EXECUTABLE, profile, url, hidden=True)
    try:
        session = b.call('Target.attachToTarget', {'targetId': b._target, 'flatten': True})['sessionId']
        deadline = time.monotonic() + 60
        filled = False
        while time.monotonic() < deadline:
            if not filled:
                script = FILL_KEYCLOAK % (json.dumps(os.environ['CAM_USER']), json.dumps(os.environ['CAM_PASSWORD']))
                result = b.call('Runtime.evaluate', {'expression': script, 'returnByValue': True}, session)
                filled = result.get('result', {}).get('value') is True
            passport = b.cookie('cam_passport', discovery.cognos_root(os.environ.get('COGNOS_URL') or url)
                                .split('//')[1].split('/')[0].split(':')[0])
            if passport:
                return passport
            time.sleep(0.5)
        raise AssertionError('no cam_passport after signing in')
    finally:
        b.close()


def test_the_namespace_is_found_to_sign_in_in_the_browser():
    method = discovery.resolve_method(connection())
    assert method.kind == 'browser'


def test_signs_in_in_the_browser_and_logs_in_to_tm1_with_the_passport(tmp_path):
    method = discovery.resolve_method(connection())
    url = discovery.browser_login_url(method.dispatcher, connection().namespace)
    passport = sign_in_as_the_user(url, str(tmp_path / 'profile'))
    with build_client(connection(), None, method='browser', passport=lambda: passport) as client:
        user = client.users.active_user().name
    assert user == 'CAMID("{}:u:{}")'.format(connection().namespace, os.environ['CAM_USER'])


def test_the_hidden_try_gives_up_quickly_when_the_provider_needs_the_user(tmp_path):
    # Keycloak keeps its login session in a cookie that ends with the browser, so a new browser
    # needs the user again: the hidden window should notice in seconds, not wait out its timeout
    method = discovery.resolve_method(connection())
    url = discovery.browser_login_url(method.dispatcher, connection().namespace)
    host = discovery.cognos_root(method.dispatcher).split('//')[1].split('/')[0].split(':')[0]
    b = browser.Browser(EXECUTABLE, str(tmp_path / 'profile'), url, hidden=True)
    try:
        started = time.monotonic()
        home = discovery.cognos_root(method.dispatcher).split('//')[1].split('/')[0]
        assert browser.wait_for_cookie(b, 'cam_passport', host, browser.SILENT_TIMEOUT,
                                       give_up_when_user_needed=True, home=home) is None
        assert time.monotonic() - started < browser.SILENT_TIMEOUT - 3
    finally:
        b.close()
