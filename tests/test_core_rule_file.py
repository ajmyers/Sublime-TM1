"""core.rule_file: the .rux file."""

import pytest

import core_samples
from snapshot import matches_snapshot
from tm1pkg.core.rule_file import rules_to_text, text_to_rules


@pytest.mark.parametrize('sample', core_samples.CUBES)
def test_writes_the_same_file_as_before(sample):
    matches_snapshot(sample + '.rux', rules_to_text(*core_samples.CUBES[sample]))


def test_a_rule_put_with_its_header_comes_back_with_one_header():
    name, dimensions, rules = core_samples.CUBES['sales_cube']
    text = rules_to_text(name, dimensions, rules)
    assert rules_to_text(name, dimensions, text_to_rules(text)) == text


def test_a_cube_without_rules_writes_just_the_header():
    assert rules_to_text('Empty', ['A'], None).startswith('#' * 79 + '\n### Cube: Empty')


def test_put_sends_the_file_with_unix_line_endings_and_one_final_newline():
    assert text_to_rules('\r\nA;\r\nB;\r\n\r\n') == 'A;\nB;\n'
