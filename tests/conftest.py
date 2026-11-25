import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.join(ROOT, 'tests', 'stubs'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))


# The repository is a Sublime Text package: its modules import each other relatively, under the
# package's name. Tests import it as `tm1pkg`.
package = types.ModuleType('tm1pkg')
package.__path__ = [ROOT]
sys.modules['tm1pkg'] = package


import pytest  # noqa: E402


class FakeStore:
    """The credential store, in memory: no test reaches the real Keychain or Credential Manager."""
    name = 'Keychain'

    def __init__(self):
        self.secrets, self.fail = {}, False

    def _check(self):
        if self.fail:
            raise OSError('the store is locked')

    def get(self, account):
        self._check()
        return self.secrets.get(account)

    def store(self, account, secret):
        self._check()
        self.secrets[account] = secret

    def delete(self, account):
        self._check()
        self.secrets.pop(account, None)


@pytest.fixture(autouse=True)
def credential_store(monkeypatch):
    from tm1pkg.core import keychain

    from tm1pkg.plugin import credentials

    store = FakeStore()
    monkeypatch.setattr(keychain, '_store', lambda platform=None: store)
    # The store is used off the UI thread; in tests, at once
    monkeypatch.setattr(credentials, '_background', lambda fn: fn())
    return store
