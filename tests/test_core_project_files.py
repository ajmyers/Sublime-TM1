"""core.project_files: the rule and process files Get keeps in the project."""

import os

import core_samples
from tm1pkg.core.project_files import mirror

SALES = ('Sales', ['Region', 'Year', 'Sandboxes'], "['Margin'] = N: 1;")
NO_RULES = ('Empty', ['A'], '')


def files(folder):
    return sorted(os.path.relpath(os.path.join(d, f), folder).replace(os.sep, '/')
                  for d, _, names in os.walk(folder) for f in names)


def test_writes_rules_and_processes_to_their_folders(tmp_path):
    counts = mirror(str(tmp_path), [SALES, NO_RULES], [core_samples.cube_view(), core_samples.odbc()])
    assert files(tmp_path) == ['processes/Copy Plan.pro', 'processes/Extract Orders.pro', 'rules/Sales.rux']
    assert counts == (1, 2, 0)


def test_deletes_what_the_server_no_longer_has(tmp_path):
    mirror(str(tmp_path), [SALES], [core_samples.cube_view(), core_samples.odbc()])
    assert mirror(str(tmp_path), [], [core_samples.odbc()]) == (0, 1, 2)
    assert files(tmp_path) == ['processes/Extract Orders.pro']


def test_deletes_files_version_0_1_left_in_the_root_folder(tmp_path):
    (tmp_path / 'Old.pro').write_text('x')
    (tmp_path / 'Old.rux').write_text('x')
    mirror(str(tmp_path), [], [core_samples.odbc()])
    assert files(tmp_path) == ['processes/Extract Orders.pro']


def test_leaves_the_users_other_files_alone(tmp_path):
    (tmp_path / 'processes').mkdir()
    (tmp_path / 'processes' / 'notes.txt').write_text('x')
    (tmp_path / 'rules').mkdir()
    (tmp_path / 'rules' / 'draft.pro').write_text('x')
    (tmp_path / 'Project.sublime-project').write_text('{}')
    mirror(str(tmp_path), [], [])
    assert files(tmp_path) == ['Project.sublime-project', 'processes/notes.txt', 'rules/draft.pro']
