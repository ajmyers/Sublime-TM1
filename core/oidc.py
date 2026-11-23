"""Signing in with OpenID Connect in the user's browser, for TM1 in CAM security behind a Cognos
OIDC namespace.

The flow is the one for native apps (RFC 8252): the authorization code flow with PKCE (RFC 7636),
redirecting to a one-shot listener on 127.0.0.1 at a free port. The ID token it yields goes to
skipcheck-tm1's cognos_id_token, which exchanges it with Cognos for a CAM passport at each TM1
login. Tokens are kept in memory only.

``OidcSignIn.id_token`` is what cognos_id_token calls: the current ID token while it's valid, a new
one from the refresh token once it isn't, and otherwise a new sign-in in the browser. It runs on the
gateway's worker thread, so the editor stays usable while the user signs in.
"""

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser

# Seconds before its expiry that an ID token is treated as expired: Cognos must still accept it
EXPIRY_MARGIN = 60
# How long to wait for the user to finish signing in
SIGN_IN_TIMEOUT = 300

DONE_PAGE = '''<!doctype html><meta charset="utf-8"><title>Signed in to TM1</title>
<body style="font-family: system-ui, sans-serif; margin: 3em">
<h2>{title}</h2><p>{message}</p><p>You can close this tab and go back to Sublime Text.</p>'''


class SignInError(Exception):
    """Signing in didn't give an ID token: refused, cancelled, timed out, or a misconfigured provider."""


def pkce_pair():
    """A code verifier and its S256 challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def claims(id_token):
    """The claims of a JWT, unverified: only to read its expiry. Cognos verifies the token."""
    try:
        payload = id_token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


class _Callback(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        result = {key: values[0] for key, values in query.items()}
        if 'code' not in result and 'error' not in result:
            self.send_response(404)
            self.end_headers()
            return
        self.server.result = result
        ok = 'code' in result and result.get('state') == self.server.state
        page = DONE_PAGE.format(
            title='Signed in to TM1' if ok else 'Sign-in failed',
            message='Sublime Text can now connect.' if ok else (result.get('error_description')
                                                                  or result.get('error') or 'Unexpected answer.'))
        body = page.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class LoopbackRedirect:
    """A listener on 127.0.0.1 at a free port, for the one redirect that ends a sign-in."""

    def __init__(self, state):
        self._server = http.server.HTTPServer(('127.0.0.1', 0), _Callback)
        self._server.state = state
        self._server.result = None
        self._server.timeout = 0.5
        self.uri = 'http://127.0.0.1:{}/callback'.format(self._server.server_port)

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        try:
            while self._server.result is None and time.monotonic() < deadline:
                self._server.handle_request()
        finally:
            self._server.server_close()
        return self._server.result


class OidcSignIn:
    """The tokens of one sign-in, renewed as needed. One per project connection."""

    def __init__(self, issuer, client_id, client_secret=None, scopes='openid', verify=True,
                 open_browser=webbrowser.open, on_browser=None, http=None, clock=time.time):
        self.issuer = issuer.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret or None
        self.scopes = scopes if 'openid' in scopes.split() else 'openid ' + scopes
        self._verify = verify
        self._open_browser = open_browser
        self._on_browser = on_browser
        self._http = http
        self._clock = clock
        self._config = None
        self._tokens = {}
        self._lock = threading.Lock()

    # The callable for skipcheck_tm1.auth.cognos_id_token

    def id_token(self):
        with self._lock:
            token = self._tokens.get('id_token')
            if token and self._still_valid(token):
                return token
            if self._tokens.get('refresh_token'):
                try:
                    return self._store(self._token_request({'grant_type': 'refresh_token',
                                                            'refresh_token': self._tokens['refresh_token']}))
                except SignInError:
                    self._tokens = {}
            return self._store(self._sign_in())

    def forget(self):
        with self._lock:
            self._tokens = {}

    def _still_valid(self, token):
        expiry = claims(token).get('exp')
        return expiry is None or self._clock() < expiry - EXPIRY_MARGIN

    def _store(self, tokens):
        if 'id_token' not in tokens:
            raise SignInError('{} gave no ID token: is "openid" among the scopes?'.format(self.issuer))
        self._tokens = tokens
        return tokens['id_token']

    # The provider

    def _client(self):
        if self._http is not None:
            return self._http
        import httpx2

        return httpx2.Client(verify=self._verify, timeout=30)

    def configuration(self):
        if self._config is None:
            url = self.issuer + '/.well-known/openid-configuration'
            response = self._client().get(url)
            if response.status_code != 200:
                raise SignInError('No OpenID Connect configuration at {} (HTTP {})'.format(url, response.status_code))
            self._config = response.json()
        return self._config

    def _token_request(self, data):
        data = dict(data, client_id=self.client_id)
        if self.client_secret:
            data['client_secret'] = self.client_secret
        response = self._client().post(self.configuration()['token_endpoint'], data=data)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code != 200:
            raise SignInError('{} refused the token request: {}'.format(
                self.issuer, body.get('error_description') or body.get('error') or response.status_code))
        return body

    def authorization_url(self, redirect_uri, state, challenge, nonce):
        query = {'response_type': 'code', 'client_id': self.client_id, 'redirect_uri': redirect_uri,
                 'scope': self.scopes, 'state': state, 'nonce': nonce,
                 'code_challenge': challenge, 'code_challenge_method': 'S256'}
        return self.configuration()['authorization_endpoint'] + '?' + urllib.parse.urlencode(query)

    def _sign_in(self):
        state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        verifier, challenge = pkce_pair()
        redirect = LoopbackRedirect(state)
        url = self.authorization_url(redirect.uri, state, challenge, nonce)
        if self._on_browser is not None:
            self._on_browser(url)
        self._open_browser(url)
        result = redirect.wait(SIGN_IN_TIMEOUT)
        if result is None:
            raise SignInError('Signing in at {} timed out after {} seconds.'.format(self.issuer, SIGN_IN_TIMEOUT))
        if 'error' in result:
            raise SignInError('{} refused the sign-in: {}'.format(
                self.issuer, result.get('error_description') or result['error']))
        if result.get('state') != state:
            raise SignInError('The sign-in came back with the wrong state; try again.')
        tokens = self._token_request({'grant_type': 'authorization_code', 'code': result['code'],
                                      'redirect_uri': redirect.uri, 'code_verifier': verifier})
        if claims(tokens.get('id_token', '')).get('nonce') not in (None, nonce):
            raise SignInError('The ID token is for another sign-in (its nonce differs); try again.')
        return tokens
