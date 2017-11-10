import os
import tempfile

from base64 import urlsafe_b64decode, urlsafe_b64encode

from TM1py import TM1Service
from TM1py.Exceptions import TM1pyException


def get_tm1_service(settings):
    address = settings['ServerAddress']
    port = settings['PortNumber']
    user = settings['UserName']
    ssl = True if settings['UseSSL'] == 'T' else False
    password = decode("1234567890", settings['Password'])
    namespace = settings['CAMNamespaceID']

    session_name = '{}_{}_{}_{}'.format(address, port, user, namespace)

    cookie_path = tempfile.gettempdir()
    cookie_file = os.path.join(cookie_path, urlsafe_b64encode(session_name.encode()).decode() + ".tm1_session")

    namespace = None if len(namespace) == 0 else namespace

    connected = False
    if os.path.isfile(cookie_file):
        try:
            service = TM1Service.restore_from_file(cookie_file)
            service._tm1_rest._get_cookies()
            connected = True
        except TM1pyException as e:
            pass

    if not connected:
        try:
            service = TM1Service(address=address, port=port, user=user, password=password, namespace=namespace, ssl=ssl)
            connected = True
        except TM1pyException as e:
            raise

    service.save_to_file(cookie_file)

    return service


def decode(key, enc):
    dec = []
    enc = urlsafe_b64decode(enc).decode()
    for i in range(len(enc)):
        key_c = key[i % len(key)]
        dec_c = chr((256 + ord(enc[i]) - ord(key_c)) % 256)
        dec.append(dec_c)
    return "".join(dec)
