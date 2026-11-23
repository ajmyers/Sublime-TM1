"""core.connection: the project's connection settings, and their migration from earlier versions."""

import base64

import pytest

from tm1pkg.core.connection import (
    Connection,
    NotConfigured,
    build_client,
    from_project_settings,
    has_stored_password,
    with_connection,
    without_stored_passwords,
)

CURRENT = {'tm1': {'address': 'tm1.example.com', 'port': '8010', 'user': 'admin', 'ssl': True,
                   'namespace': '', 'verify': True, 'async_requests': True}}

# What CreateNewTm1Project wrote: the password obfuscated with a fixed key
TM1_CONNECTION = {'tm1_connection': {'address': 'tm1.example.com', 'port': '8010', 'user': 'admin', 'ssl': True,
                                     'password': 'kZaQkQ==', 'namespace': 'LDAP', 'async_requests_mode': False},
                  'format_process_on_update': True}

# The format before that
TM1_CONNECTION_SETTINGS = {'TM1ConnectionSettings': {'ServerAddress': 'tm1', 'PortNumber': 5001, 'UserName': 'admin',
                                                     'UseSSL': 'F', 'Password': 'x', 'CAMNamespaceID': '',
                                                     'UseAsync': 'T'}}


def test_reads_the_current_settings():
    connection = from_project_settings(CURRENT)
    assert connection == Connection(address='tm1.example.com', port='8010', user='admin', ssl=True)
    assert connection.base_url == 'https://tm1.example.com:8010/api/v1/'


def test_reads_the_settings_earlier_versions_wrote():
    assert from_project_settings(TM1_CONNECTION) == Connection(
        address='tm1.example.com', port='8010', user='admin', ssl=True, namespace='LDAP', verify=False,
        async_requests=False)
    assert from_project_settings(TM1_CONNECTION_SETTINGS) == Connection(
        address='tm1', port='5001', user='admin', ssl=False, verify=False, async_requests=True)


def test_projects_from_0_2_keep_their_certificates_unchecked_and_new_ones_check():
    # TM1py never checked certificates: an upgrade mustn't break a self-signed one
    assert from_project_settings(TM1_CONNECTION).verify is False
    assert from_project_settings(CURRENT).verify is True
    assert from_project_settings({'tm1': {'address': 'h', 'port': '1', 'user': 'u'}}).verify is True


def test_a_port_with_a_path_is_the_ibm_cloud_rest_api():
    connection = Connection(address='acme.planning-analytics.ibmcloud.com', port='443/tm1/api/tm1', user='u', ssl=True)
    assert connection.base_url == 'https://acme.planning-analytics.ibmcloud.com:443/tm1/api/tm1/api/v1/'


def test_saving_the_connection_keeps_the_earlier_packages_settings():
    # So a teammate still on 0.2.x can use the same project
    settings = with_connection(TM1_CONNECTION, from_project_settings(TM1_CONNECTION))
    assert settings['tm1_connection'] == TM1_CONNECTION['tm1_connection']
    assert settings['format_process_on_update'] is True
    assert 'password' not in settings['tm1']
    assert from_project_settings(settings) == from_project_settings(TM1_CONNECTION)


def test_finds_and_removes_the_passwords_the_earlier_package_stored():
    assert has_stored_password(TM1_CONNECTION) and has_stored_password(TM1_CONNECTION_SETTINGS)
    assert not has_stored_password(CURRENT)
    for settings in (TM1_CONNECTION, TM1_CONNECTION_SETTINGS):
        cleaned = without_stored_passwords(settings)
        assert not has_stored_password(cleaned)
        assert from_project_settings(cleaned) == from_project_settings(settings)


def test_a_project_without_a_connection_says_how_to_make_one():
    with pytest.raises(NotConfigured, match='Create New TM1 Project'):
        from_project_settings({'format_process_on_update': True})


def test_describes_who_connects_without_the_password():
    assert Connection(address='h', port='1', user='u', namespace='LDAP').describe() == 'LDAP\\u at http://h:1/api/v1/'


def logged_in_with(connection, password):
    """The Authorization header the client logs in with."""
    import httpx2

    seen = []

    def handler(request):
        seen.append(request.headers.get('Authorization'))
        return httpx2.Response(200, json={'ID': 1}, headers={'Set-Cookie': 'TM1SessionId=abc; Path=/api/'})

    client = build_client(connection, password, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    try:
        client.session.login()
    finally:
        client.close()
    return seen[0]


def test_logs_in_with_basic_authentication_without_a_namespace():
    header = logged_in_with(Connection(address='h', port='1', user='admin'), 'apple')
    assert header == 'Basic ' + base64.b64encode(b'admin:apple').decode()


def test_logs_in_with_cam_when_the_project_has_a_namespace():
    header = logged_in_with(Connection(address='h', port='1', user='alice', namespace='LDAP'), 'secret')
    assert header == 'CAMNamespace ' + base64.b64encode(b'alice:secret:LDAP').decode()
