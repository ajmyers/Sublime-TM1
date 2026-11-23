"""core.setup: the server the user types, and the settings it becomes."""

import pytest

from tm1pkg.core.setup import parse_server, project_settings


@pytest.mark.parametrize('typed, parsed', [
    ('tm1.example.com', ('tm1.example.com', None, None)),
    ('tm1.example.com:8010', ('tm1.example.com', '8010', None)),
    ('https://tm1.example.com:8010/api/v1/', ('tm1.example.com', '8010', True)),
    ('http://localhost:18011', ('localhost', '18011', False)),
    ('https://acme.planning-analytics.ibmcloud.com/tm1/api/tm1/', ('acme.planning-analytics.ibmcloud.com',
                                                                    '443/tm1/api/tm1', True)),
    ('https://tm1.example.com', ('tm1.example.com', None, True)),
])
def test_reads_a_host_or_a_url(typed, parsed):
    assert parse_server(typed) == parsed


def test_settings_hold_no_password_and_only_the_overrides_given():
    settings = project_settings('tm1', '8010', True, False, 'alice', 'LDAP', 'cam')
    assert settings == {'address': 'tm1', 'port': '8010', 'ssl': True, 'verify': False, 'user': 'alice',
                        'namespace': 'LDAP', 'async_requests': True, 'auth': 'cam'}
    assert 'dispatcher' in project_settings('tm1', 1, False, True, dispatcher='http://c:9300')
