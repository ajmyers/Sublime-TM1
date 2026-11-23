"""core.discovery, against a mock TM1 and Cognos that answer as the real ones did."""

import httpx2
import pytest

from tm1pkg.core import discovery
from tm1pkg.core.connection import Connection

LDAP_PROMPT = {'promptInfo': {'displayObjects': [
    {'name': 'CAMNamespace', 'type': 'hidden', 'value': 'LDAP'},
    {'name': 'CAMUsername', 'type': 'text'}, {'name': 'CAMPassword', 'type': 'textnoecho'}]}}
OIDC_PROMPT = {'promptInfo': {'displayObjects': [
    {'name': 'camRedirectURL', 'type': 'redirect', 'value': 'http://idp/auth?client_id=cognos'},
    {'name': 'CAMNamespace', 'type': 'hidden', 'value': 'OIDC'}]}}
NAMESPACES = {'promptInfo': {'displayObjects': [{'name': 'CAMNamespace', 'type': 'singleselect', 'promptOptions': [
    {'isDefault': False, 'value': 'LDAP'}, {'isDefault': True, 'value': 'OIDC'}]}]}}


def mock(cam=True):
    def handler(request):
        url = str(request.url)
        if '/api/v1/' in url and 'tm1' in request.url.host:
            headers = [('WWW-Authenticate', 'CAMPassport http://cognos:9300/bi/v1/disp'),
                       ('WWW-Authenticate', 'CAMNamespace')] if cam else [('WWW-Authenticate', 'Basic realm="TM1"')]
            return httpx2.Response(401, headers=headers)
        if url.endswith('/bi/v1/login'):
            return httpx2.Response(441, json=NAMESPACES)
        if 'CAMNamespace=LDAP' in url:
            return httpx2.Response(441, json=LDAP_PROMPT)
        if 'CAMNamespace=OIDC' in url:
            return httpx2.Response(441, json=OIDC_PROMPT)
        return httpx2.Response(404)
    return httpx2.Client(transport=httpx2.MockTransport(handler))


def test_reads_tm1s_challenge():
    assert discovery.challenge('http://tm1:8010/api/v1/', client=mock(cam=False)) == discovery.Challenge('basic')
    assert discovery.challenge('http://tm1:8010/api/v1/', client=mock()) == \
        discovery.Challenge('cam', 'http://cognos:9300/bi/v1/disp')


def test_lists_cognos_namespaces_default_first_and_how_each_logs_on():
    client = mock()
    assert discovery.namespaces('http://cognos:9300/bi/v1/disp', client=client) == ['OIDC', 'LDAP']
    assert discovery.login_kind('http://cognos:9300/bi/v1/disp', 'LDAP', client=client) == 'password'
    assert discovery.login_kind('http://cognos:9300/bi/v1/disp', 'OIDC', client=client) == 'browser'


@pytest.mark.parametrize('given, root', [
    ('http://c:9300/bi/v1/disp', 'http://c:9300/bi'),
    ('https://c/ibmcognos/bi/v1/disp', 'https://c/ibmcognos/bi'),
    ('https://c/ibmcognos/cgi-bin/cognos.cgi', 'https://c/ibmcognos/bi'),
    ('https://c/ibmcognos/cgi-bin/cognosisapi.dll', 'https://c/ibmcognos/bi'),
    ('http://c:9300/p2pd/servlet/dispatch', 'http://c:9300/bi'),
    ('http://c:9300', 'http://c:9300/bi'),
])
def test_finds_cognos_from_each_form_of_clientcamuri(given, root):
    assert discovery.cognos_root(given) == root


def test_the_browser_signs_in_at_cognos_for_the_namespace():
    url = discovery.browser_login_url('http://c:9300/bi/v1/disp', 'Azure AD')
    assert url == 'http://c:9300/bi/?CAMNamespace=Azure%20AD'


def connection(**fields):
    return Connection(**dict(dict(address='tm1', port='8010', user=''), **fields))


def test_resolves_how_to_log_in():
    client = mock()
    assert discovery.resolve_method(connection(), client=mock(cam=False)) == discovery.Method('basic')
    assert discovery.resolve_method(connection(namespace='OIDC'), client=client) == \
        discovery.Method('browser', 'http://cognos:9300/bi/v1/disp')
    assert discovery.resolve_method(connection(namespace='LDAP'), client=client) == \
        discovery.Method('cam', 'http://cognos:9300/bi/v1/disp')


def test_the_projects_dispatcher_and_method_win():
    client = mock()
    overridden = connection(namespace='OIDC', dispatcher='http://localhost:19300')
    resolved = discovery.resolve_method(overridden, client=client)
    assert resolved == discovery.Method('browser', 'http://localhost:19300')
    assert discovery.resolve_method(connection(namespace='OIDC', auth='cam'), client=client).kind == 'cam'


def test_falls_back_from_https_on_a_tls_failure_only():
    def client_for(verify):
        def handler(request):
            if request.url.scheme == 'https':
                raise httpx2.ConnectError('[SSL: WRONG_VERSION_NUMBER] wrong version number', request=request)
            return httpx2.Response(401)
        return httpx2.Client(transport=httpx2.MockTransport(handler))
    assert discovery.probe_scheme('tm1', 8010, client_for=client_for) == discovery.Scheme(ssl=False)
    with pytest.raises(discovery.Downgrade):
        discovery.probe_scheme('tm1', 8010, pinned_ssl=True, client_for=client_for)


def test_an_untrusted_certificate_is_https_not_a_fallback():
    def client_for(verify):
        def handler(request):
            raise httpx2.ConnectError('[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate', request=request)
        return httpx2.Client(transport=httpx2.MockTransport(handler))
    assert discovery.probe_scheme('tm1', 8010, client_for=client_for) == discovery.Scheme(ssl=True, trusted=False)


def test_nothing_listening_is_an_error_not_a_fallback():
    def client_for(verify):
        def handler(request):
            raise httpx2.ConnectError('[Errno 61] Connection refused', request=request)
        return httpx2.Client(transport=httpx2.MockTransport(handler))
    with pytest.raises(discovery.DiscoveryError, match="Couldn't reach"):
        discovery.probe_scheme('tm1', 8010, client_for=client_for)


def test_lists_the_admin_servers_servers():
    def handler(request):
        if request.url.port == 5898:
            raise httpx2.ConnectError('refused', request=request)
        return httpx2.Response(200, json={'value': [{'Name': 'Planning', 'HTTPPortNumber': 8010, 'UsingSSL': True},
                                                    {'Name': 'agent', 'HTTPPortNumber': 0}]})
    servers = discovery.admin_servers('tm1', client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    assert servers == [discovery.Server('Planning', 8010, True)]
