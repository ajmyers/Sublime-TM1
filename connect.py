import os
import sys
import pickle
import requests
import tempfile

from base64 import b64decode, urlsafe_b64decode, urlsafe_b64encode

sys.path.append(os.path.join(os.path.dirname(__file__), 'include/TM1py'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'include/prettytable'))

from TM1py import TM1Service, RESTService
from TM1py.Exceptions import TM1pyException


def get_tm1_service(settings):
    RESTService._get_cookies = _get_cookies

    address = settings['ServerAddress']
    port = settings['PortNumber']
    user = settings['UserName']
    ssl = True if settings['UseSSL'] == 'T' else False
    password = decode("1234567890", settings['Password'])

    if 'CAMNamespaceID' in settings:
        namespace = settings['CAMNamespaceID']
        service = TM1Service(address=address, port=port, user=user, password=password, namespace=namespace, ssl=ssl)
    else:
        service = TM1Service(address=address, port=port, user=user, password=password, ssl=ssl)

    return service


def decode(key, enc):
    dec = []
    enc = urlsafe_b64decode(enc).decode()
    for i in range(len(enc)):
        key_c = key[i % len(key)]
        dec_c = chr((256 + ord(enc[i]) - ord(key_c)) % 256)
        dec.append(dec_c)
    return "".join(dec)


# patch TM1py to support sessions
def _get_cookies(self):
    """ perform a simple GET request (Ask for the TM1 Version) to start a session
    """
    url = '{}/api/v1/Configuration/ProductVersion/$value'.format(self._base_url)

    auth_string = self._headers['Authorization'].split(" ")[1]
    auth = b64decode(auth_string).decode('ascii').split(":")
    if 'CAMNamespace' in self._headers['Authorization']:
        session_name = '{}_{}_{}'.format(self._base_url, auth[0], auth[2])
    else:
        session_name = '{}_{}'.format(self._base_url, auth[0])

    cookie_path = tempfile.gettempdir()
    cookie_file = os.path.join(cookie_path, urlsafe_b64encode(session_name.encode()).decode() + ".tm1_session")

    try:
        with open(cookie_file, 'rb') as f:
            cookies = pickle.load(f)
            requests.utils.add_dict_to_cookiejar(self._s.cookies, cookies)
            h = self._headers.copy()
            h.pop('Authorization')
            response = self._s.get(url=url, headers=h, data='', verify=self._verify)
            self.verify_response(response)
            self._version = response.text
            return
    except TM1pyException as e:
        print('Bad cookie, generating new session')
    except Exception as e:
        print('No cookie or some other error, generating new session')
        pass

    response = self._s.get(url=url, headers=self._headers, data='', verify=self._verify)
    self.verify_response(response)
    self._version = response.text

    with open(cookie_file, 'wb') as f:
        pickle.dump(requests.utils.dict_from_cookiejar(self._s.cookies), f)
