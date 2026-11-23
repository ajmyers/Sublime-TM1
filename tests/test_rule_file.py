"""The .rux file: a header naming the cube's dimensions, then the rules."""

import pytest

import samples
from tm1pkg.pelle import Utils
from snapshot import matches_snapshot

CUBES = {f.__name__: f for f in samples.ALL_CUBES}


@pytest.mark.parametrize('sample', CUBES)
def test_writes_the_file_it_always_has(sample):
    matches_snapshot(sample + '.rux', Utils.cube_rule_to_text(CUBES[sample]()))


def test_leaves_out_the_sandboxes_dimension():
    assert 'Sandboxes' not in Utils.cube_rule_to_text(samples.sales_cube())


def test_a_rule_put_with_its_header_comes_back_with_one_header():
    # Put sends the whole file, header included, so the server's rules start with the header
    text = Utils.cube_rule_to_text(samples.sales_cube())
    assert Utils.cube_rule_to_text(samples.sales_cube(rules=text)) == text
