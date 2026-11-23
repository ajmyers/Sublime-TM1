"""Discovery against the real servers: TM1's challenge, Cognos's namespaces and how they log on."""

import os

import pytest

from tm1pkg.core import discovery
from tests_live_url import url_parts


@pytest.mark.skipif(not os.environ.get('TM1_URL'), reason='no TM1 server: set TM1_URL')
def test_a_tm1_in_its_own_security_asks_for_basic_over_the_scheme_it_speaks():
    host, port, ssl = url_parts(os.environ['TM1_URL'])
    assert discovery.probe_scheme(host, port).ssl == ssl
    assert discovery.challenge(os.environ['TM1_URL']) == discovery.Challenge('basic')


@pytest.mark.skipif(not (os.environ.get('TM1_CAM_URL') and os.environ.get('CAM_NAMESPACE')),
                    reason='no CAM environment: set TM1_CAM_URL, CAM_NAMESPACE (and COGNOS_URL)')
def test_a_tm1_in_cam_security_names_cognos_whose_namespaces_say_how_they_log_on():
    challenge = discovery.challenge(os.environ['TM1_CAM_URL'])
    assert challenge.kind == 'cam' and challenge.dispatcher
    cognos = os.environ.get('COGNOS_URL') or challenge.dispatcher
    namespaces = discovery.namespaces(cognos)
    assert os.environ['CAM_NAMESPACE'] in namespaces
    assert discovery.login_kind(cognos, os.environ['CAM_NAMESPACE']) in ('browser', 'password')
