"""core.completions: the snippets Get generates. They were checked identical to 0.2.x's, over the
SData sample's 73 cubes and 117 processes, before 0.2.x's code was removed; tests/snapshots/
completions.json holds them for the samples here, so they stay that way."""

import json

import pytest

import core_samples
from snapshot import matches_snapshot
from tm1pkg.core import completions

CUBES = [('Sales', ['Region', 'Year', 'Measure', 'Sandboxes']), ('}ClientGroups', ['}Clients', '}Groups']),
         ('P&L Report', ['Cost_Center', 'Account Lines', '}Version'])]


def test_writes_the_same_completions_as_before():
    processes = [f() for f in core_samples.ALL_PROCESSES]
    built = completions.build(CUBES, processes)
    matches_snapshot('completions.json', json.dumps(built, indent=1, ensure_ascii=False) + '\n')


def test_builds_rule_and_ti_completions_in_the_earlier_order():
    processes = [core_samples.cube_view(), core_samples.odbc()]
    built = completions.build(CUBES[:2], processes)
    assert [c['trigger'] for c in built[completions.RULE]] == ['DB-Sales', 'DB-ClientGroups']
    triggers = [c['trigger'] for c in built[completions.TI]]
    assert triggers[:2] == ['EXECUTEPROCESS-Copy Plan', 'EXECUTEPROCESS-Extract Orders']
    assert triggers[2:4] == ['CELLGETN-Sales', 'CELLGETN-}ClientGroups']
    assert triggers[-2:] == ['_LOCALS-Sales', '_LOCALS-}ClientGroups']


def test_a_cube_with_only_sandboxes_gets_locals_for_its_value():
    # 0.2.x raised NameError here
    assert '${1:nValue}_l' in completions.cube_locals('Odd', ['Sandboxes'])['completion']


@pytest.mark.parametrize('completion, generated', [
    (completions.db('Sales', ['Region']), True),
    ({'trigger': 'mine', 'completion': 'x', 'details': 'my own'}, False),
    ('plain string completion', False),
])
def test_tells_generated_completions_from_a_users_own(completion, generated):
    assert completions.is_generated(completion) is generated
