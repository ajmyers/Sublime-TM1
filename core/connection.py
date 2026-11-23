"""A project's TM1 connection: what the project file holds, and the client made from it.

The project file holds where TM1 is and who connects, never a secret: the password is asked for
when the project first connects, and kept only in memory (plugin/credentials.py).

Projects made by 0.2.x hold the connection under "tm1_connection" (or, older still,
"TM1ConnectionSettings"), with an obfuscated password. ``from_project_settings`` reads them, so a
project works after the upgrade as it is. They're never removed, so a teammate still on 0.2.x
(Sublime Text before 4213) can use the same project: ``with_connection`` adds the connection under
"tm1" and keeps them, and only ``without_stored_passwords`` removes their passwords, when the user
asks. Their certificates stay unchecked, as TM1py never checked them: turning checking on is the
user's choice, not something an upgrade does to them.
"""

from dataclasses import asdict, dataclass

KEY = 'tm1'
LEGACY_KEYS = ('tm1_connection', 'TM1ConnectionSettings')

SESSION_CONTEXT = 'Sublime Text TM1'


@dataclass(frozen=True)
class Connection:
    address: str
    port: str
    user: str
    ssl: bool = False
    # A CAM namespace: CAM security (TM1 security modes 4 and 5) instead of TM1's own
    namespace: str = ''
    # Whether to check the server's certificate (True), not to (False), or a CA bundle to check it with
    verify: object = True
    # Run processes asynchronously and poll (TM1 11.x and later), rather than in one long request
    async_requests: bool = True
    # How to log in: "basic" (TM1's own security), "cam" (a user and password for a CAM namespace) or
    # "browser" (sign in in a browser window, for a CAM passport). Empty: worked out at connection,
    # from TM1 and Cognos (plugin/gateway.py)
    auth: str = ''
    # Cognos's address, when the one TM1 gives (its ClientCAMURI) isn't reachable from here
    dispatcher: str = ''

    @property
    def base_url(self):
        # A port can carry a path: IBM Cloud's REST API is at 443/tm1/api/<server>
        scheme = 'https' if self.ssl else 'http'
        return '{}://{}:{}/api/v1/'.format(scheme, self.address, self.port)

    @property
    def uses_cam(self):
        return bool(self.namespace)

    def describe(self):
        who = '{}\\{}'.format(self.namespace, self.user) if self.uses_cam else self.user
        return '{} at {}'.format(who, self.base_url)

    def to_settings(self):
        return asdict(self)


class NotConfigured(Exception):
    """The project has no TM1 connection."""


def from_project_settings(settings):
    """The connection in a project's "settings", in any of the formats it has been saved in."""
    settings = settings or {}
    if isinstance(settings.get(KEY), dict):
        return _from_current(settings[KEY])
    if isinstance(settings.get('tm1_connection'), dict):
        return _from_tm1_connection(settings['tm1_connection'])
    if isinstance(settings.get('TM1ConnectionSettings'), dict):
        return _from_tm1_connection_settings(settings['TM1ConnectionSettings'])
    raise NotConfigured('This project has no TM1 connection: run "TM1: Config - Create New TM1 Project".')


def with_connection(settings, connection):
    """The project's settings with the connection under "tm1". The earlier package's blocks stay."""
    result = dict(settings or {})
    result[KEY] = connection.to_settings()
    return result


def has_stored_password(settings):
    """Whether the earlier package's settings hold a password (obfuscated, not encrypted)."""
    settings = settings or {}
    return bool((settings.get('tm1_connection') or {}).get('password')
                or (settings.get('TM1ConnectionSettings') or {}).get('Password'))


def without_stored_passwords(settings):
    """The project's settings with the passwords the earlier package stored removed. That package
    then asks for no password and fails to connect, so this is for users who've moved on from it."""
    result = dict(settings or {})
    if isinstance(result.get('tm1_connection'), dict):
        result['tm1_connection'] = {k: v for k, v in result['tm1_connection'].items() if k != 'password'}
    if isinstance(result.get('TM1ConnectionSettings'), dict):
        result['TM1ConnectionSettings'] = {k: v for k, v in result['TM1ConnectionSettings'].items()
                                           if k != 'Password'}
    return result


METHODS = ('basic', 'cam', 'browser')


def _from_current(data):
    auth = data.get('auth') or ''
    return Connection(
        address=data['address'], port=str(data['port']), user=data.get('user', ''),
        ssl=bool(data.get('ssl', False)), namespace=data.get('namespace') or '',
        verify=data.get('verify', True), async_requests=bool(data.get('async_requests', True)),
        # An unknown method (such as an earlier build's "oidc") is worked out again
        auth=auth if auth in METHODS else '', dispatcher=data.get('dispatcher') or '',
    )


def _from_tm1_connection(data):
    return Connection(
        address=data['address'], port=str(data['port']), user=data.get('user', ''),
        ssl=bool(data.get('ssl', False)), namespace=data.get('namespace') or '', verify=False,
        async_requests=bool(data.get('async_requests_mode', True)),
    )


def _from_tm1_connection_settings(data):
    return Connection(
        address=data['ServerAddress'], port=str(data['PortNumber']), user=data.get('UserName', ''),
        ssl=data.get('UseSSL') == 'T', namespace=data.get('CAMNamespaceID') or '', verify=False,
        async_requests=data.get('UseAsync', 'F') == 'T',
    )


def default_method(connection):
    """The method when nothing has been worked out: what 0.2.x did."""
    return connection.auth or ('cam' if connection.namespace else 'basic')


def authenticator(connection, method, password=None, passport=None):
    """skipcheck-tm1's authenticator for a method. ``passport`` is a callable giving a CAM passport,
    for "browser"; skipcheck-tm1 calls it at each TM1 login."""
    from skipcheck_tm1.auth import basic, cam_namespace, cam_passport

    if method == 'browser':
        return cam_passport(passport)
    if method == 'cam':
        return cam_namespace(connection.user, password or '', connection.namespace)
    return basic(connection.user, password)


def build_client(connection, password, http_client=None, method=None, passport=None):
    """A skipcheck-tm1 client for the connection. Nothing is sent until its first request."""
    from skipcheck_tm1 import Tm1Client

    builder = Tm1Client.builder().base_url(connection.base_url).session_context(SESSION_CONTEXT)
    builder = builder.authenticator(authenticator(connection, method or default_method(connection), password, passport))
    builder = builder.verify(connection.verify)
    if http_client is not None:
        builder = builder.http_client(http_client)
    return builder.build()
