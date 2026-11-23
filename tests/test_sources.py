"""Checks of the package's own source files."""

import glob
import os
import warnings

import pytest

from conftest import ROOT

SOURCES = sorted(
    os.path.relpath(path, ROOT)
    for pattern in ['*.py', 'core/*.py', 'plugin/*.py']
    for path in glob.glob(os.path.join(ROOT, pattern), recursive=True)
)


@pytest.mark.parametrize('source', SOURCES)
def test_compiles_without_syntax_warnings(source):
    # Sublime Text 4213+ runs plugins on Python 3.14, where an invalid escape such as '\\s' in a
    # plain string is a SyntaxWarning, and a future Python makes it an error
    with open(os.path.join(ROOT, source), encoding='utf-8') as f:
        code = f.read()
    with warnings.catch_warnings():
        warnings.simplefilter('error', SyntaxWarning)
        compile(code, source, 'exec')
