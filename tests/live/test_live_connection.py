"""core.connection against a real TM1."""

import dataclasses
import os

import pytest

from tm1pkg.core.connection import Connection, build_client
from tests_live_url import url_parts

URL = os.environ.get('TM1_URL')
pytestmark = pytest.mark.skipif(not URL, reason='no TM1 server: set TM1_URL (and TM1_USER, TM1_PASSWORD)')


def connection():
    address, port, ssl = url_parts(URL)
    return Connection(address=address, port=port, user=os.environ.get('TM1_USER', 'admin'), ssl=ssl, verify=False)


def test_connects_with_the_right_password():
    with build_client(connection(), os.environ.get('TM1_PASSWORD', '')) as client:
        assert client.processes.list(select='Name')


def test_a_wrong_password_is_refused_as_a_credential_problem():
    from skipcheck_tm1.errors import Tm1AuthenticationError, Tm1ErrorKind

    # A user that doesn't exist: TM1 locks a real user out after a few failed logins
    # (SystemServerClientExceedMaxLogonNumber), and every run of this test would count
    nobody = dataclasses.replace(connection(), user='sublime-tm1-test-nobody')
    with build_client(nobody, 'not the password') as client:
        with pytest.raises(Tm1AuthenticationError) as refused:
            client.processes.list(select='Name')
    assert refused.value.kind == Tm1ErrorKind.CREDENTIAL_REJECTED
