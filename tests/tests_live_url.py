"""Splits TM1_URL (http://host:port/api/v1/) into a project's address, port and SSL."""

from urllib.parse import urlsplit


def url_parts(url):
    parts = urlsplit(url)
    path = parts.path.rstrip('/')
    if path.endswith('/api/v1'):
        path = path[:-len('/api/v1')]
    port = str(parts.port or (443 if parts.scheme == 'https' else 80)) + path
    return parts.hostname, port, parts.scheme == 'https'
