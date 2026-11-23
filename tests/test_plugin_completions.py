"""plugin.completions: Get's completions from the cache, and the project's own."""

import pytest
import sublime

from fakes import FakeView, FakeWindow
from tm1pkg.core import completions as generated
from tm1pkg.plugin import completions

PROJECT = '/p/sales.sublime-project'


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sublime, '_cache_path', str(tmp_path))
    completions._items.clear()
    yield
    completions._items.clear()


def offered(scope, project_data=None):
    window = FakeWindow(project=project_data or {}, project_file=PROJECT)
    view = FakeView(window=window, scope=scope)
    items = completions.ProjectCompletions().on_query_completions(view, '', [0]) or []
    return [i.trigger for i in items]


def store_sales():
    completions.store(PROJECT, generated.build([('Sales', ['Region'])], []))


def test_offers_rule_completions_in_rules_and_ti_ones_in_processes():
    store_sales()
    assert offered('source.tm1.rule') == ['DB-Sales']
    assert 'CELLGETN-Sales' in offered('source.tm1.ti') and 'DB-Sales' not in offered('source.tm1.ti')
    assert offered('text.plain') == []


def test_items_are_snippets():
    store_sales()
    window = FakeWindow(project={}, project_file=PROJECT)
    view = FakeView(window=window, scope='source.tm1.rule')
    item = completions.ProjectCompletions().on_query_completions(view, '', [0])[0]
    assert item.completion_format == sublime.COMPLETION_FORMAT_SNIPPET and item.kind == sublime.KIND_SNIPPET


def test_a_new_get_replaces_the_earlier_completions():
    store_sales()
    offered('source.tm1.rule')
    completions.store(PROJECT, generated.build([('Plan', ['Version'])], []))
    assert offered('source.tm1.rule') == ['DB-Plan']


def test_still_offers_the_projects_own_completions_as_0_2_did():
    own = {'completions': {'source.tm1.ti': [{'trigger': 'mine', 'completion': 'x'}], 'source.tm1.rule': ['plain']}}
    assert offered('source.tm1.ti', own) == ['mine']
    assert offered('source.tm1.rule', own) == ['plain']
    assert offered('source.tm1.ti', {'completions': [{'trigger': 'anywhere', 'completion': 'y'}]}) == ['anywhere']


def test_a_window_without_a_project_gets_nothing():
    view = FakeView(window=FakeWindow(), scope='source.tm1.rule')
    assert completions.ProjectCompletions().on_query_completions(view, '', [0]) is None


def test_removes_only_what_0_2s_get_generated_from_the_project():
    mine = {'trigger': 'mine', 'completion': 'x'}
    data = {'folders': [], 'completions': {'source.tm1.rule': [generated.db('Sales', ['Region']), mine],
                                           'source.tm1.ti': [generated.db('Sales', ['Region'])]}}
    assert completions.without_generated(data) == {'folders': [], 'completions': {'source.tm1.rule': [mine]}}
    assert completions.without_generated({'completions': {'source.tm1.rule': [generated.db('S', ['R'])]}}) == {}
    assert completions.without_generated({'completions': {'source.tm1.rule': [mine]}}) is None
    assert completions.without_generated({}) is None
