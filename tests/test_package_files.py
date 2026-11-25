"""Files Sublime Text reads from the package itself."""

import json
import os
import subprocess

from conftest import ROOT


def test_python_version_is_exactly_a_version_sublime_accepts():
    # Sublime Text doesn't strip the file: "3.14\n" is "an invalid version", and it then ignores
    # every plugin in the package. Editors like to add that newline back.
    with open(os.path.join(ROOT, '.python-version'), 'rb') as f:
        content = f.read()
    assert content == b'3.14'


def test_every_message_package_control_shows_is_in_the_package():
    # Package Control shows messages.json's entries on install and upgrade, from the built package:
    # a file export-ignored (.gitattributes) or missing would be an error there, not here
    with open(os.path.join(ROOT, 'messages.json'), encoding='utf-8') as f:
        messages = json.load(f)
    assert messages
    for key, path in messages.items():
        assert key == 'install' or all(part.isdigit() for part in key.split('.')), key
        assert os.path.isfile(os.path.join(ROOT, path)), path
        ignored = subprocess.run(['git', 'check-attr', 'export-ignore', '--', path], cwd=ROOT,
                                 capture_output=True, text=True, check=True).stdout
        assert not ignored.strip().endswith(': set'), path


def test_messages_fit_package_controls_view():
    with open(os.path.join(ROOT, 'messages.json'), encoding='utf-8') as f:
        paths = json.load(f).values()
    for path in paths:
        with open(os.path.join(ROOT, path), encoding='utf-8') as f:
            assert all(len(line) <= 79 for line in f.read().split('\n')), path
