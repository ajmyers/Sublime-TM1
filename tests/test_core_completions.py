"""core.completions: the snippets Get generates, the same as the earlier version's."""

import pytest
import sublime

import core_samples
import samples
from tm1pkg.core import completions
from tm1pkg.pelle import Utils

CUBES = [('Sales', ['Region', 'Year', 'Measure', 'Sandboxes']), ('}ClientGroups', ['}Clients', '}Groups']),
         ('P&L Report', ['Cost_Center', 'Account Lines', '}Version'])]


def legacy(completion):
    """A completion the earlier version made, in the form core.completions makes them."""
    result = dict(completion)
    assert result.pop('completion_format') == sublime.COMPLETION_FORMAT_SNIPPET
    assert result.pop('kind') == sublime.KIND_SNIPPET
    return result


def new(completion):
    result = dict(completion)
    assert result.pop('completion_format') == 'snippet' and result.pop('kind') == 'snippet'
    return result


class LegacyCube:
    def __init__(self, name, dimensions):
        self.name, self.dimensions = name, dimensions


@pytest.mark.parametrize('cube', CUBES, ids=[c[0] for c in CUBES])
def test_cube_completions_match_the_earlier_version(cube):
    name, dimensions = cube
    old = LegacyCube(name, dimensions)
    assert new(completions.db(name, dimensions)) == legacy(Utils.generate_rule_completion(old))
    old_locals = Utils.generate_turbo_integrator_cube_locals_completion(old)
    assert new(completions.cube_locals(name, dimensions)) == legacy(old_locals)
    for function in completions.CUBE_FUNCTIONS:
        assert new(completions.cube_function(name, dimensions, function)) == \
            legacy(Utils.generate_turbo_integrator_cube_completion(old, function))


@pytest.mark.parametrize('sample', ['no_datasource', 'parameters_and_variables'])
def test_execute_process_matches_the_earlier_version(sample):
    old = getattr(samples, sample)()
    assert new(completions.execute_process(getattr(core_samples, sample)())) == \
        legacy(Utils.generate_turbo_integrator_completion(old))


def test_builds_rule_and_ti_completions_in_the_earlier_order():
    processes = [core_samples.cube_view(), core_samples.odbc()]
    built = completions.build(CUBES[:2], processes)
    assert [c['trigger'] for c in built[completions.RULE]] == ['DB-Sales', 'DB-ClientGroups']
    triggers = [c['trigger'] for c in built[completions.TI]]
    assert triggers[:2] == ['EXECUTEPROCESS-Copy Plan', 'EXECUTEPROCESS-Extract Orders']
    assert triggers[2:4] == ['CELLGETN-Sales', 'CELLGETN-}ClientGroups']
    assert triggers[-2:] == ['_LOCALS-Sales', '_LOCALS-}ClientGroups']


def test_a_cube_with_only_sandboxes_gets_locals_for_its_value():
    # The earlier version raised NameError here
    assert '${1:nValue}_l' in completions.cube_locals('Odd', ['Sandboxes'])['completion']


def test_tells_generated_completions_from_a_users_own():
    assert completions.is_generated(completions.db('Sales', ['Region']))
    assert not completions.is_generated({'trigger': 'mine', 'completion': 'x', 'details': 'my own'})
    assert not completions.is_generated('plain string completion')
