"""Live tests: run against the TM1 server TM1_URL names (with TM1_USER and TM1_PASSWORD), the same
settings the skipcheck-tm1 live tests read. Skipped without it.

IBM's SData sample is what they're written against: for instance, from skipcheck-tm1's
docker/tm1-server, ``docker compose --profile samples up -d`` serves it on port 8011 as admin/apple.
"""

import os

import pytest

URL = os.environ.get('TM1_URL')


@pytest.fixture(scope='session')
def tm1():
    if not URL:
        pytest.skip('no TM1 server: set TM1_URL (and TM1_USER, TM1_PASSWORD)')
    from skipcheck_tm1 import Tm1Client
    client = Tm1Client.builder().base_url(URL).basic_auth(os.environ.get('TM1_USER', 'admin'),
                                                          os.environ.get('TM1_PASSWORD', '')).build()
    yield client
    client.close()
