"""core/ runs without Sublime Text: none of it imports sublime or sublime_plugin."""

import ast
import glob
import os

import pytest

from conftest import ROOT

CORE = sorted(glob.glob(os.path.join(ROOT, 'core', '**', '*.py'), recursive=True))


@pytest.mark.parametrize('path', CORE, ids=lambda p: os.path.relpath(p, ROOT))
def test_does_not_import_sublime(path):
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split('.')[0])
    assert not imported & {'sublime', 'sublime_plugin'}
