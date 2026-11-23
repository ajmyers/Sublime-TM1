"""Setting up a project's connection: what the user typed, and the settings it becomes."""

from urllib.parse import urlsplit


def parse_server(text):
    """A host, or a URL: (host, port or None, ssl or None). A URL's path goes on the port, as IBM
    Cloud's REST API is at 443/tm1/api/<server>: ``https://acme.planning-analytics.ibmcloud.com/tm1/api/tm1/``
    gives ('acme...', '443/tm1/api/tm1', True)."""
    text = text.strip()
    if '://' not in text:
        host, _, port = text.partition(':')
        return host.strip('/'), (port.strip('/') or None), None
    parts = urlsplit(text)
    ssl = parts.scheme == 'https'
    path = parts.path.rstrip('/')
    if path.endswith('/api/v1'):
        path = path[:-len('/api/v1')]
    port = parts.port or (443 if ssl else 80)
    return parts.hostname, '{}{}'.format(port, path) if (parts.port or path) else None, ssl


def project_settings(host, port, ssl, verify, user='', namespace='', auth='', dispatcher=''):
    """The "tm1" settings of a project: where TM1 is and how to log in, never a password."""
    settings = {'address': host, 'port': str(port), 'ssl': bool(ssl), 'verify': verify, 'user': user,
                'namespace': namespace, 'async_requests': True}
    if auth:
        settings['auth'] = auth
    if dispatcher:
        settings['dispatcher'] = dispatcher
    return settings
