"""Files Sublime Text reads from the package itself."""

import os

from conftest import ROOT


def test_python_version_is_exactly_a_version_sublime_accepts():
    # Sublime Text doesn't strip the file: "3.14\n" is "an invalid version", and it then ignores
    # every plugin in the package. Editors like to add that newline back.
    with open(os.path.join(ROOT, '.python-version'), 'rb') as f:
        content = f.read()
    assert content == b'3.14'
