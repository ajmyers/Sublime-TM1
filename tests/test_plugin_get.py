"""TM1: Get, on the gateway."""

import os
from types import SimpleNamespace

import pytest
import sublime

import core_samples
from fakes import FakeWindow
from tm1pkg.core import completions as generated
from tm1pkg.plugin import completions, gateway, get


class FakeClient:
    def __init__(self, cubes, processes):
        self.cubes = SimpleNamespace(list=lambda **options: cubes)
        self.processes = SimpleNamespace(list=lambda **options: processes)


class FakeGateway:
    """Runs the work at once, as the real gateway does on a worker thread."""

    def __init__(self, client):
        self.client = client
        self.connection = SimpleNamespace(base_url='http://tm1:8010/api/v1/')

    def run(self, window, work, on_done=None, on_error=None):
        on_done(work(self.client))


def cube(name, dimensions, rules):
    return SimpleNamespace(name=name, dimensions=[SimpleNamespace(name=d) for d in dimensions], rules=rules)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(sublime, '_cache_path', str(tmp_path / 'cache'))
    completions._items.clear()
    client = FakeClient([cube('Sales', ['Region', 'Sandboxes'], 'SKIPCHECK;'), cube('Plan', ['Version'], None)],
                        [core_samples.cube_view()])
    monkeypatch.setattr(gateway, 'for_window', lambda window, quiet=False: FakeGateway(client))
    project_file = str(tmp_path / 'sales.sublime-project')
    legacy = generated.db('Old', ['X'])
    window = FakeWindow(project={'folders': [{'path': 'model'}], 'completions': {'source.tm1.rule': [legacy]}},
                        project_file=project_file)
    return window, tmp_path


def test_writes_the_files_in_the_project_folder_relative_to_the_project_file(setup):
    window, root = setup
    get.GetObjectsFromServer(window).run()
    assert sorted(os.listdir(root / 'model' / 'rules')) == ['Sales.rux']
    assert sorted(os.listdir(root / 'model' / 'processes')) == ['Copy Plan.pro']


def test_stores_completions_outside_the_project_and_removes_0_2s_from_it(setup):
    window, _ = setup
    get.GetObjectsFromServer(window).run()
    assert 'completions' not in window.project
    triggers = [i.trigger for items in completions._generated_items(window.project_file_name()).values() for i in items]
    assert 'DB-Sales' in triggers and 'DB-Plan' in triggers and 'DB-Old' not in triggers


def test_says_what_it_got(setup):
    window, _ = setup
    get.GetObjectsFromServer(window).run()
    assert window.statuses[-1] == 'TM1: got 1 rules and 1 processes'


def test_a_project_without_a_folder_says_how_to_add_one(setup, monkeypatch):
    window, _ = setup
    window.project = {'folders': []}
    sublime.dialogs.clear()
    get.GetObjectsFromServer(window).run()
    assert 'Add Folder to Project' in sublime.dialogs[-1]


def test_is_enabled_only_in_a_project():
    assert not get.GetObjectsFromServer(FakeWindow()).is_enabled()
    assert get.GetObjectsFromServer(FakeWindow(project_file='/p/x.sublime-project')).is_enabled()
