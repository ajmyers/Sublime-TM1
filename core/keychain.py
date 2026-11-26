"""The operating system's credential store, for a password the user asked to remember.

macOS: the login Keychain, through Security.framework (ctypes). Windows: Credential Manager, through
advapi32 (ctypes). Linux: the Secret Service (GNOME Keyring, KWallet), through secret-tool, with the
password on its stdin. No libraries: keyring isn't in Package Control's channel.

Nothing here raises. A store that's missing, locked or refusing is printed to the console and
answered with None or False, and the caller asks for the password as it would without one: a
failure here never blocks a connection.
"""

import ctypes
import shutil
import subprocess
import sys

SERVICE = 'Sublime Text TM1'
TIMEOUT = 10


def _log(action, error):
    print('TM1: the credential store could not {} ({}); the password is asked instead'.format(action, error))


class _MacKeychain:
    name = 'Keychain'
    NOT_FOUND = -25300

    def __init__(self):
        from ctypes import POINTER, byref, c_char_p, c_int32, c_uint32, c_void_p  # noqa: F401

        self._byref = byref
        security = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        foundation = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self._find = security.SecKeychainFindGenericPassword
        self._find.argtypes = [c_void_p, c_uint32, c_char_p, c_uint32, c_char_p, POINTER(c_uint32),
                               POINTER(c_void_p), POINTER(c_void_p)]
        self._find.restype = c_int32
        self._add = security.SecKeychainAddGenericPassword
        self._add.argtypes = [c_void_p, c_uint32, c_char_p, c_uint32, c_char_p, c_uint32, c_char_p,
                              POINTER(c_void_p)]
        self._add.restype = c_int32
        self._modify = security.SecKeychainItemModifyAttributesAndData
        self._modify.argtypes = [c_void_p, c_void_p, c_uint32, c_char_p]
        self._modify.restype = c_int32
        self._delete = security.SecKeychainItemDelete
        self._delete.argtypes = [c_void_p]
        self._delete.restype = c_int32
        self._free = security.SecKeychainItemFreeContent
        self._free.argtypes = [c_void_p, c_void_p]
        self._release = foundation.CFRelease
        self._release.argtypes = [c_void_p]
        self._c_uint32, self._c_void_p = c_uint32, c_void_p

    def _item(self, account, want_secret):
        service, account = SERVICE.encode(), account.encode()
        length, data, item = self._c_uint32(), self._c_void_p(), self._c_void_p()
        status = self._find(None, len(service), service, len(account), account,
                            self._byref(length) if want_secret else None,
                            self._byref(data) if want_secret else None, self._byref(item))
        if status == self.NOT_FOUND:
            return None, None
        if status != 0:
            raise OSError('Security.framework error {}'.format(status))
        secret = None
        if want_secret:
            secret = ctypes.string_at(data, length.value).decode('utf-8')
            self._free(None, data)
        return item, secret

    def get(self, account):
        item, secret = self._item(account, True)
        if item is not None:
            self._release(item)
        return secret

    def store(self, account, secret):
        data = secret.encode('utf-8')
        item, _ = self._item(account, False)
        if item is not None:
            try:
                status = self._modify(item, None, len(data), data)
            finally:
                self._release(item)
        else:
            service, name = SERVICE.encode(), account.encode()
            status = self._add(None, len(service), service, len(name), name, len(data), data, None)
        if status != 0:
            raise OSError('Security.framework error {}'.format(status))

    def delete(self, account):
        item, _ = self._item(account, False)
        if item is None:
            return
        try:
            status = self._delete(item)
        finally:
            self._release(item)
        if status != 0:
            raise OSError('Security.framework error {}'.format(status))


class _WindowsCredentials:
    name = 'Credential Manager'
    GENERIC = 1
    PERSIST_LOCAL_MACHINE = 2
    NOT_FOUND = 1168

    def __init__(self):
        from ctypes import POINTER, Structure, byref, c_void_p, c_wchar_p
        from ctypes.wintypes import BOOL, DWORD, FILETIME, LPBYTE

        class Credential(Structure):
            _fields_ = [('Flags', DWORD), ('Type', DWORD), ('TargetName', c_wchar_p), ('Comment', c_wchar_p),
                        ('LastWritten', FILETIME), ('CredentialBlobSize', DWORD), ('CredentialBlob', LPBYTE),
                        ('Persist', DWORD), ('AttributeCount', DWORD), ('Attributes', c_void_p),
                        ('TargetAlias', c_wchar_p), ('UserName', c_wchar_p)]

        self._Credential, self._byref, self._LPBYTE = Credential, byref, LPBYTE
        advapi = ctypes.WinDLL('advapi32', use_last_error=True)
        self._read = advapi.CredReadW
        self._read.argtypes = [c_wchar_p, DWORD, DWORD, POINTER(POINTER(Credential))]
        self._read.restype = BOOL
        self._write = advapi.CredWriteW
        self._write.argtypes = [POINTER(Credential), DWORD]
        self._write.restype = BOOL
        self._delete = advapi.CredDeleteW
        self._delete.argtypes = [c_wchar_p, DWORD, DWORD]
        self._delete.restype = BOOL
        self._free = advapi.CredFree
        self._free.argtypes = [c_void_p]
        self._pointer = POINTER(Credential)

    @staticmethod
    def _target(account):
        return '{}: {}'.format(SERVICE, account)

    def _error(self):
        return OSError('Credential Manager error {}'.format(ctypes.get_last_error()))

    def get(self, account):
        found = self._pointer()
        if not self._read(self._target(account), self.GENERIC, 0, self._byref(found)):
            if ctypes.get_last_error() == self.NOT_FOUND:
                return None
            raise self._error()
        try:
            credential = found.contents
            return ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize).decode('utf-16-le')
        finally:
            self._free(found)

    def store(self, account, secret):
        blob = secret.encode('utf-16-le')
        buffer = ctypes.create_string_buffer(blob, len(blob))
        credential = self._Credential(Type=self.GENERIC, TargetName=self._target(account), UserName=account,
                                      CredentialBlobSize=len(blob),
                                      CredentialBlob=ctypes.cast(buffer, self._LPBYTE),
                                      Persist=self.PERSIST_LOCAL_MACHINE)
        if not self._write(self._byref(credential), 0):
            raise self._error()

    def delete(self, account):
        if not self._delete(self._target(account), self.GENERIC, 0) and ctypes.get_last_error() != self.NOT_FOUND:
            raise self._error()


class _SecretTool:
    name = 'keyring'

    def __init__(self):
        self._tool = shutil.which('secret-tool')
        if self._tool is None:
            raise OSError('secret-tool not found (it comes with libsecret-tools)')

    def _run(self, *args, secret=None):
        return subprocess.run([self._tool, *args, 'service', SERVICE, 'account', self._account], input=secret,
                              capture_output=True, text=True, timeout=TIMEOUT)

    def get(self, account):
        self._account = account
        result = self._run('lookup')
        # secret-tool lookup exits 1, saying nothing, when there's no such secret
        if result.returncode != 0:
            if result.stderr.strip():
                raise OSError(result.stderr.strip())
            return None
        return result.stdout or None

    def store(self, account, secret):
        self._account = account
        result = self._run('store', '--label', '{}: {}'.format(SERVICE, account), secret=secret)
        if result.returncode != 0:
            raise OSError(result.stderr.strip() or 'secret-tool store exited {}'.format(result.returncode))

    def delete(self, account):
        self._account = account
        result = self._run('clear')
        if result.returncode != 0 and result.stderr.strip():
            raise OSError(result.stderr.strip())


_backend = None
_backend_tried = False


def _store(platform=None):
    global _backend, _backend_tried
    if not _backend_tried:
        _backend_tried = True
        platform = platform or sys.platform
        try:
            if platform == 'darwin':
                _backend = _MacKeychain()
            elif platform == 'win32':
                _backend = _WindowsCredentials()
            else:
                _backend = _SecretTool()
        except Exception as e:
            print('TM1: no credential store to remember passwords in ({})'.format(e))
            _backend = None
    return _backend


def available():
    """Whether there's a store to offer."""
    return _store() is not None


def name():
    """What the store is called on this system: Keychain, Credential Manager or keyring."""
    store = _store()
    return store.name if store is not None else 'keychain'


def get(account):
    """The stored password, or None: none stored, or the store failed."""
    store = _store()
    if store is None:
        return None
    try:
        return store.get(account)
    except Exception as e:
        _log('read the password', e)
        return None


def store(account, secret):
    """Stores the password; whether it did."""
    backend = _store()
    if backend is None:
        return False
    try:
        backend.store(account, secret)
        return True
    except Exception as e:
        _log('store the password', e)
        return False


def delete(account):
    """Removes the stored password, if any; whether nothing's left stored."""
    backend = _store()
    if backend is None:
        return True
    try:
        backend.delete(account)
        return True
    except Exception as e:
        _log('remove the password', e)
        return False
