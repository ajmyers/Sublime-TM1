"""TM1: Get - Pull Objects from Server: the files it leaves in the project."""

import os

import samples
from pelle.Pelle import mirror_objects


def files(folder):
    return sorted(os.path.relpath(os.path.join(d, f), folder) for d, _, names in os.walk(folder) for f in names)


def test_writes_rules_and_processes_to_their_folders(tmp_path):
    mirror_objects(str(tmp_path), [samples.sales_cube()], [samples.cube_view(), samples.odbc()])
    assert files(tmp_path) == ['processes/Copy Plan.pro', 'processes/Extract Orders.pro', 'rules/Sales.rux']


def test_leaves_out_cubes_without_rules(tmp_path):
    cube = samples.sales_cube(rules='')
    mirror_objects(str(tmp_path), [cube], [])
    assert files(tmp_path) == []


def test_deletes_what_the_server_no_longer_has(tmp_path):
    mirror_objects(str(tmp_path), [samples.sales_cube(), samples.control_cube()], [samples.cube_view(), samples.odbc()])
    mirror_objects(str(tmp_path), [samples.sales_cube()], [samples.odbc()])
    assert files(tmp_path) == ['processes/Extract Orders.pro', 'rules/Sales.rux']


def test_deletes_files_earlier_versions_left_in_the_root_folder(tmp_path):
    (tmp_path / 'Old.pro').write_text('x')
    (tmp_path / 'Old.rux').write_text('x')
    mirror_objects(str(tmp_path), [], [samples.odbc()])
    assert files(tmp_path) == ['processes/Extract Orders.pro']


def test_leaves_the_users_other_files_alone(tmp_path):
    (tmp_path / 'processes').mkdir()
    (tmp_path / 'processes' / 'notes.txt').write_text('x')
    (tmp_path / 'rules').mkdir()
    (tmp_path / 'rules' / 'draft.pro').write_text('x')
    (tmp_path / 'Project.sublime-project').write_text('{}')
    mirror_objects(str(tmp_path), [], [])
    assert files(tmp_path) == ['Project.sublime-project', 'processes/notes.txt', 'rules/draft.pro']
