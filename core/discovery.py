"""Working out how to reach and log in to a TM1 server from its host, asking only the servers.

Everything here is unauthenticated: no credentials go into a probe. Each step asks one server
something it tells anyone:

- the TM1 Admin Server lists its servers, with their REST ports and whether they use SSL;
- a port speaks HTTPS or HTTP, never both, and HTTPS on an HTTP port fails at once;
- TM1's 401 says how it wants to be logged in to: WWW-Authenticate Basic (TM1's own security), or
  CAMPassport with Cognos's address (its ClientCAMURI) and CAMNamespace (CAM security);
- Cognos's login lists its namespaces, and for each, either the user and password it prompts for,
  or the redirect a browser follows to sign in.
"""

import re
from dataclasses import dataclass

ADMIN_HTTPS, ADMIN_HTTP = 5898, 5895
PROBE_PATH = 'api/v1/Configuration/ProductVersion/$value'
TIMEOUT = 10


class DiscoveryError(Exception):
    """A server didn't answer as TM1, its Admin Server or Cognos would."""


class Downgrade(DiscoveryError):
    """A server that spoke HTTPS now speaks only HTTP: not followed, as that's how a password could be
    read on the way."""


@dataclass(frozen=True)
class Server:
    name: str
    port: int
    ssl: bool


@dataclass(frozen=True)
class Scheme:
    ssl: bool
    # False: TLS works but the certificate isn't trusted (IBM's self-signed one, say)
    trusted: bool = True


@dataclass(frozen=True)
class Challenge:
    # "basic" (TM1's own security) or "cam"
    kind: str
    # Cognos's address as TM1 gives it (ClientCAMURI), for "cam"
    dispatcher: str = ''


def _client(verify=True):
    import httpx2

    return httpx2.Client(verify=verify, timeout=TIMEOUT, follow_redirects=False)


def _is_tls_failure(error):
    """Whether an error is TLS failing (this port doesn't speak HTTPS), as opposed to a certificate
    that isn't trusted, or nothing listening."""
    text = str(error) + str(getattr(error, '__cause__', '') or '')
    if 'CERTIFICATE_VERIFY_FAILED' in text:
        return False
    return any(sign in text for sign in ('WRONG_VERSION_NUMBER', 'wrong version number', 'protocol version',
                                         'UNEXPECTED_EOF', 'unexpected eof', 'record layer failure',
                                         'packet length too long', 'EOF occurred in violation'))


def _untrusted(error):
    return 'CERTIFICATE_VERIFY_FAILED' in str(error) + str(getattr(error, '__cause__', '') or '')


def admin_servers(host, client=None, ports=(ADMIN_HTTPS, ADMIN_HTTP)):
    """The TM1 servers the host's Admin Server knows, by name: HTTPS (5898) first, then HTTP
    (5895). Empty when there's no Admin Server to ask. The list is only names and ports, so its
    certificate isn't checked."""
    import httpx2

    client = client or _client(verify=False)
    for scheme, port in (('https', ports[0]), ('http', ports[1])):
        try:
            response = client.get('{}://{}:{}/api/v1/Servers'.format(scheme, host, port))
        except httpx2.HTTPError:
            continue
        if response.status_code == 200:
            servers = [Server(s['Name'], int(s['HTTPPortNumber']), bool(s.get('UsingSSL')))
                       for s in response.json().get('value', []) if s.get('HTTPPortNumber')]
            return sorted(servers, key=lambda s: s.name.lower())
    return []


def probe_scheme(host, port, pinned_ssl=None, client_for=_client):
    """Whether the port speaks HTTPS (and whether its certificate is trusted) or HTTP. HTTPS is
    tried first. When the project has pinned HTTPS (``pinned_ssl`` True), plain HTTP is refused."""
    import httpx2

    url = 'https://{}:{}/{}'.format(host, port, PROBE_PATH)
    try:
        client_for(True).get(url)
        return Scheme(ssl=True)
    except httpx2.HTTPError as e:
        if _untrusted(e):
            return Scheme(ssl=True, trusted=False)
        if not _is_tls_failure(e):
            raise DiscoveryError("Couldn't reach TM1 at {}:{}: {}".format(host, port, e)) from e
    if pinned_ssl:
        raise Downgrade('TM1 at {}:{} used to speak HTTPS and now speaks only HTTP. Not connecting: '
                        "check with the server's administrator.".format(host, port))
    try:
        client_for(True).get('http://{}:{}/{}'.format(host, port, PROBE_PATH))
    except httpx2.HTTPError as e:
        raise DiscoveryError("Couldn't reach TM1 at {}:{}: {}".format(host, port, e)) from e
    return Scheme(ssl=False)


def challenge(base_url, verify=True, client=None):
    """How TM1 asks to be logged in to, from the WWW-Authenticate headers of its 401."""
    response = (client or _client(verify)).get(base_url.rstrip('/') + '/Configuration/ServerName')
    headers = response.headers.get_list('www-authenticate') if hasattr(response.headers, 'get_list') else \
        [response.headers.get('www-authenticate', '')]
    for header in headers:
        match = re.match(r'\s*CAMPassport\s+(\S+)', header, re.IGNORECASE)
        if match:
            return Challenge('cam', match.group(1))
    if any(h.strip().lower().startswith('campassport') or h.strip().lower() == 'camnamespace' for h in headers):
        return Challenge('cam')
    if response.status_code in (401, 403) or any(h.strip().lower().startswith('basic') for h in headers):
        return Challenge('basic')
    raise DiscoveryError('{} answered {} without saying how to log in: is it TM1?'.format(
        base_url, response.status_code))


def cognos_root(dispatcher):
    """Cognos's web root (ending in /bi) from the forms a ClientCAMURI takes: .../bi/v1/disp,
    .../bi, a gateway's .../cgi-bin/cognos.cgi, or a dispatcher's .../p2pd/servlet/dispatch."""
    url = dispatcher.rstrip('/')
    match = re.match(r'(.*?/bi)(/.*)?$', url)
    if match:
        return match.group(1)
    match = re.match(r'(.*)/cgi-bin/cognos(isapi)?\.(cgi|dll)$', url, re.IGNORECASE)
    if match:
        return match.group(1) + '/bi'
    match = re.match(r'(.*)/p2pd(/.*)?$', url)
    if match:
        return match.group(1) + '/bi'
    return url + '/bi'


def dispatcher_base(dispatcher):
    """Cognos's address without /bi, as skipcheck-tm1's Cognos logon takes it."""
    return re.sub(r'/bi$', '', cognos_root(dispatcher))


def _login(dispatcher, query, verify, client):
    response = (client or _client(verify)).get(cognos_root(dispatcher) + '/v1/login', params=query)
    try:
        return response.json().get('promptInfo', {}).get('displayObjects', [])
    except ValueError as e:
        raise DiscoveryError('{} is not a Cognos login (HTTP {})'.format(
            cognos_root(dispatcher), response.status_code)) from e


def namespaces(dispatcher, verify=True, client=None):
    """Cognos's namespaces, the default first."""
    for item in _login(dispatcher, {}, verify, client):
        if item.get('name') == 'CAMNamespace':
            if item.get('type') == 'hidden':
                return [item.get('value')]
            options = item.get('promptOptions') or []
            return [o['value'] for o in sorted(options, key=lambda o: not o.get('isDefault'))]
    return []


def login_kind(dispatcher, namespace, verify=True, client=None):
    """How the namespace logs a user on: "password" (Cognos prompts for a user and password) or
    "browser" (it sends the browser to sign in elsewhere: OIDC, SAML...)."""
    items = _login(dispatcher, {'CAMNamespace': namespace}, verify, client)
    names = {item.get('name') for item in items}
    if any(item.get('type') == 'redirect' for item in items):
        return 'browser'
    if {'CAMUsername', 'CAMPassword'} <= names:
        return 'password'
    return 'browser'


def browser_login_url(dispatcher, namespace):
    """Where a browser signs in to the namespace, ending at Cognos with its cam_passport set."""
    from urllib.parse import quote

    return cognos_root(dispatcher) + '/?CAMNamespace=' + quote(namespace)


@dataclass(frozen=True)
class Method:
    # "basic", "cam" (a user and password) or "browser" (a passport from a browser sign-in)
    kind: str
    # Cognos's address, for "browser"
    dispatcher: str = ''


def resolve_method(connection, client=None):
    """How to log in to the connection's TM1, asking TM1 and Cognos. An explicit method in the
    project wins; without a namespace it's TM1's own security; with one, Cognos says whether the
    namespace prompts for a password or signs in through the browser."""
    if connection.auth:
        dispatcher = connection.dispatcher
        if connection.auth == 'browser' and not dispatcher:
            dispatcher = challenge(connection.base_url, connection.verify, client).dispatcher
        return Method(connection.auth, dispatcher)
    if not connection.namespace:
        return Method('basic')
    dispatcher = connection.dispatcher or challenge(connection.base_url, connection.verify, client).dispatcher
    if not dispatcher:
        return Method('cam')
    kind = login_kind(dispatcher, connection.namespace, connection.verify, client)
    return Method('browser' if kind == 'browser' else 'cam', dispatcher)
