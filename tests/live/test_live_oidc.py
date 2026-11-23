"""Browser sign-in against a real provider, Cognos and TM1 in CAM security. Skipped unless
TM1_OIDC_URL names such a TM1, with OIDC_ISSUER, OIDC_CLIENT_ID, COGNOS_URL, OIDC_USER and
OIDC_PASSWORD. skipcheck-tm1's pa-setup starts one: Cognos with oidc, cam.namespace oidc.

The "browser" signs in on the provider's login page the way a user would (it fills in Keycloak's
form), then follows the redirect to the package's loopback listener: everything after that is the
real flow.
"""

import os
import re
import threading
from html import unescape

import pytest

from tm1pkg.core.connection import Connection, build_client
from tests_live_url import url_parts

SETTINGS = ['TM1_OIDC_URL', 'OIDC_ISSUER', 'OIDC_CLIENT_ID', 'COGNOS_URL', 'OIDC_USER', 'OIDC_PASSWORD']
pytestmark = pytest.mark.skipif(not all(os.environ.get(s) for s in SETTINGS),
                                reason='no OIDC environment: set ' + ', '.join(SETTINGS))


@pytest.fixture(autouse=True)
def quick_timeout(monkeypatch):
    # A sign-in that goes wrong fails in seconds, not after the five minutes a user gets
    from tm1pkg.core import oidc

    monkeypatch.setattr(oidc, 'SIGN_IN_TIMEOUT', 30)


def sign_in_on_keycloak(url, user, password):
    """What a user does in the browser: fills in Keycloak's login form. Returns the answer."""
    import httpx2

    with httpx2.Client(follow_redirects=False, timeout=30) as browser:
        page = browser.get(url, follow_redirects=True)
        action = unescape(re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text).group(1))
        # Keycloak's cookies are Secure, and browsers send them to http://localhost (a secure
        # context) where httpx won't: send them as a browser would
        cookies = '; '.join('{}={}'.format(c.name, c.value) for c in browser.cookies.jar)
        answer = browser.post(action, data={'username': user, 'password': password}, headers={'Cookie': cookies})
        if answer.status_code in (302, 303):
            browser.get(answer.headers['location'])  # the redirect to the loopback listener
        return answer


def keycloak_user(user, password):
    """A browser in which the user signs in on Keycloak's login form."""
    def open_browser(url):
        threading.Thread(target=sign_in_on_keycloak, args=(url, user, password)).start()
        return True
    return open_browser


def connection():
    address, port, ssl = url_parts(os.environ['TM1_OIDC_URL'])
    return Connection(address=address, port=port, user='', ssl=ssl, namespace=os.environ.get('OIDC_NAMESPACE', 'OIDC'),
                      verify=False, auth='oidc', dispatcher=os.environ['COGNOS_URL'],
                      issuer=os.environ['OIDC_ISSUER'], client_id=os.environ['OIDC_CLIENT_ID'])


def test_signs_in_in_the_browser_and_logs_in_to_tm1_with_the_passport():
    opened = []
    browser = keycloak_user(os.environ['OIDC_USER'], os.environ['OIDC_PASSWORD'])
    with build_client(connection(), None, on_browser=opened.append, open_browser=browser) as client:
        user = client.users.active_user().name
    assert user == 'CAMID("{}:u:{}")'.format(os.environ.get('OIDC_NAMESPACE', 'OIDC'), os.environ['OIDC_USER'])
    assert len(opened) == 1 and opened[0].startswith(os.environ['OIDC_ISSUER'])


def test_a_wrong_password_stays_on_the_providers_page_and_the_sign_in_times_out(monkeypatch):
    from tm1pkg.core import oidc

    monkeypatch.setattr(oidc, 'SIGN_IN_TIMEOUT', 3)
    answers = []

    def wrong(url):
        def go():
            answers.append(sign_in_on_keycloak(url, os.environ['OIDC_USER'], 'wrong'))
        threading.Thread(target=go).start()
        return True

    with build_client(connection(), None, open_browser=wrong) as client:
        with pytest.raises(Exception, match='timed out'):
            client.users.active_user()
    assert answers and answers[0].status_code == 200  # Keycloak shows its form again
