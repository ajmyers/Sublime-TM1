"""core.oidc: the browser sign-in, against a fake provider and a fake browser."""

import base64
import hashlib
import json
import urllib.parse
import urllib.request

import httpx2
import pytest

from tm1pkg.core import oidc
from tm1pkg.core.oidc import OidcSignIn, SignInError

ISSUER = 'https://idp.example.com/realms/acme'


def jwt(claims):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b'=').decode()
    return part({'alg': 'none'}) + '.' + part(claims) + '.'


class Provider:
    """An OpenID Connect provider: discovery, and a token endpoint that checks PKCE."""

    def __init__(self, clock):
        self.clock = clock
        self.requests = []
        self.challenges = {}
        self.refresh_ok = True
        self.issued = 0

    def handler(self, request):
        if request.url.path.endswith('/.well-known/openid-configuration'):
            return httpx2.Response(200, json={'authorization_endpoint': ISSUER + '/auth',
                                               'token_endpoint': ISSUER + '/token'})
        form = dict(urllib.parse.parse_qsl(request.content.decode()))
        self.requests.append(form)
        if form['grant_type'] == 'authorization_code':
            challenge = self.challenges[form['code']]
            expected = base64.urlsafe_b64encode(hashlib.sha256(form['code_verifier'].encode()).digest()).rstrip(b'=')
            if expected.decode() != challenge['code_challenge']:
                return httpx2.Response(400, json={'error': 'invalid_grant', 'error_description': 'PKCE failed'})
            return httpx2.Response(200, json=self.tokens(challenge['nonce']))
        if form['grant_type'] == 'refresh_token':
            if not self.refresh_ok:
                return httpx2.Response(400, json={'error': 'invalid_grant'})
            return httpx2.Response(200, json=self.tokens(None))
        return httpx2.Response(400, json={'error': 'unsupported_grant_type'})

    def tokens(self, nonce):
        self.issued += 1
        claims = {'sub': 'viewer', 'exp': self.clock.now + 300, 'n': self.issued}
        if nonce:
            claims['nonce'] = nonce
        return {'id_token': jwt(claims), 'refresh_token': 'r' + str(self.issued), 'token_type': 'Bearer'}


class Clock:
    now = 1_000_000.0

    def __call__(self):
        return self.now


class Browser:
    """Opens the authorization URL the way a browser would, and lets the 'user' sign in."""

    def __init__(self, provider, answer='approve'):
        self.provider, self.answer, self.opened = provider, answer, []

    def __call__(self, url):
        self.opened.append(url)
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        code = 'code' + str(len(self.opened))
        self.provider.challenges[code] = query
        if self.answer == 'approve':
            back = {'code': code, 'state': query['state']}
        elif self.answer == 'deny':
            back = {'error': 'access_denied', 'error_description': 'The user said no', 'state': query['state']}
        else:
            back = {'code': code, 'state': 'forged'}
        # The provider redirects the browser to the loopback listener, which runs in the
        # sign-in's own thread, so this request has to come from another one
        import threading
        threading.Thread(target=urllib.request.urlopen, args=(query['redirect_uri'] + '?' +
                                                               urllib.parse.urlencode(back),)).start()
        return True


@pytest.fixture
def world():
    clock = Clock()
    provider = Provider(clock)
    http = httpx2.Client(transport=httpx2.MockTransport(provider.handler))
    browser = Browser(provider)
    sign_in = OidcSignIn(ISSUER, 'tm1-app', open_browser=browser, http=http, clock=clock)
    return sign_in, provider, browser, clock


def test_signs_in_in_the_browser_with_pkce_and_a_loopback_redirect(world):
    sign_in, provider, browser, _ = world
    token = sign_in.id_token()
    assert oidc.claims(token)['sub'] == 'viewer'
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(browser.opened[0]).query))
    assert query['code_challenge_method'] == 'S256' and query['scope'] == 'openid' and query['client_id'] == 'tm1-app'
    assert query['redirect_uri'].startswith('http://127.0.0.1:')
    assert provider.requests[0]['grant_type'] == 'authorization_code'


def test_reuses_the_token_while_it_is_valid(world):
    sign_in, provider, browser, clock = world
    first = sign_in.id_token()
    clock.now += 100
    assert sign_in.id_token() == first and len(browser.opened) == 1 and len(provider.requests) == 1


def test_renews_an_expired_token_with_the_refresh_token_without_the_browser(world):
    sign_in, provider, browser, clock = world
    first = sign_in.id_token()
    clock.now += 300 - oidc.EXPIRY_MARGIN + 1
    second = sign_in.id_token()
    assert second != first and len(browser.opened) == 1
    assert provider.requests[-1] == {'grant_type': 'refresh_token', 'refresh_token': 'r1', 'client_id': 'tm1-app'}


def test_signs_in_again_when_the_refresh_token_is_refused(world):
    sign_in, provider, browser, clock = world
    sign_in.id_token()
    provider.refresh_ok = False
    clock.now += 1000
    sign_in.id_token()
    assert len(browser.opened) == 2


def test_a_refused_sign_in_says_why(world):
    sign_in, provider, browser, _ = world
    browser.answer = 'deny'
    with pytest.raises(SignInError, match='The user said no'):
        sign_in.id_token()


def test_a_redirect_with_the_wrong_state_is_rejected(world):
    sign_in, provider, browser, _ = world
    browser.answer = 'forge'
    with pytest.raises(SignInError, match='wrong state'):
        sign_in.id_token()
    assert provider.requests == []


def test_adds_openid_to_the_scopes_and_sends_a_client_secret_if_there_is_one(world):
    _, provider, browser, clock = world
    http = httpx2.Client(transport=httpx2.MockTransport(provider.handler))
    sign_in = OidcSignIn(ISSUER, 'tm1-app', client_secret='s3cret', scopes='profile', open_browser=browser,
                         http=http, clock=clock)
    sign_in.id_token()
    assert 'openid profile' in urllib.parse.unquote_plus(browser.opened[0])
    assert provider.requests[0]['client_secret'] == 's3cret'


def test_pkce_challenge_is_the_s256_of_the_verifier():
    verifier, challenge = oidc.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
