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


PACKAGE = 'TM1 Planning Analytics Developer Tools'


def edit_settings_targets(node):
    """The base_file of every edit_settings command in a .sublime-commands or .sublime-menu tree."""
    if isinstance(node, list):
        return [t for child in node for t in edit_settings_targets(child)]
    if isinstance(node, dict):
        found = [node['args']['base_file']] if node.get('command') == 'edit_settings' else []
        return found + edit_settings_targets(node.get('children', []))
    return []


def test_the_settings_are_named_after_the_package_and_the_menus_open_them():
    # Package Control's reviewer warns of a .sublime-settings named after neither the package nor a
    # syntax. The name is part of the interface: users' overrides in Packages/User go by it
    name = PACKAGE + '.sublime-settings'
    assert os.path.isfile(os.path.join(ROOT, name))
    targets = []
    for path in ('Main.sublime-menu', os.path.join('settings', 'TM1.sublime-commands')):
        with open(os.path.join(ROOT, path), encoding='utf-8') as f:
            found = edit_settings_targets(json.load(f))
        assert found, path
        targets += found
    assert set(targets) == {'${packages}/' + PACKAGE + '/' + name}
