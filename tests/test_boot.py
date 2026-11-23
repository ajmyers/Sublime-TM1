"""boot.py: Sublime registers the command and listener classes found in its namespace."""

import glob
import importlib
import os

import sublime_plugin

from conftest import ROOT

PLUGIN_CLASSES = (sublime_plugin.Command, sublime_plugin.EventListener, sublime_plugin.ViewEventListener)


def defined_plugin_classes():
    found = {}
    for path in glob.glob(os.path.join(ROOT, 'commands', '*.py')):
        module = importlib.import_module('tm1pkg.commands.' + os.path.splitext(os.path.basename(path))[0])
        for name, value in vars(module).items():
            if isinstance(value, type) and issubclass(value, PLUGIN_CLASSES) and value.__module__ == module.__name__:
                found[name] = value
    return found


def test_boot_exports_every_command_and_listener():
    boot = importlib.import_module('tm1pkg.boot')
    defined = defined_plugin_classes()
    assert sorted(boot.__all__) == sorted(defined)
    for name, cls in defined.items():
        assert getattr(boot, name) is cls
