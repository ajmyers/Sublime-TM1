"""TM1: Put against a real TM1: errors land on the file's own lines."""

from tm1pkg.core import process_file, rule_file
from tm1pkg.plugin import put

NAME = 'zz sublime-tm1 put test'
MARK = '### PROLOG: ' + '#' * 67 + '\n\n'


def test_a_process_with_an_error_is_put_and_the_error_is_on_its_line(tm1):
    text = process_file.process_to_text(tm1.processes.get('create_Y2Ksales_cube'))
    text = text.replace(MARK, MARK + "nOk = 1;\nthis is not TI;\n", 1)
    try:
        errors = put.put_process(NAME, text)(tm1)
        assert len(errors) == 1
        assert text.split('\n')[errors[0][0]] == 'this is not TI;'
        errors = put.put_process(NAME, text.replace('this is not TI;\n', ''))(tm1)  # updates it
        assert errors == []
    finally:
        tm1.processes.delete(NAME)


def test_parameters_keep_their_type_and_value_through_a_put(tm1):
    """The typed writes don't send a parameter's type: TM1 takes it from the value."""
    import core_samples

    text = process_file.process_to_text(core_samples.parameters_and_variables())
    try:
        for _ in ('create', 'update'):
            assert put.put_process(NAME, text)(tm1) == []
            parameters = {p.name: (p.type.value, p.value) for p in
                          tm1.processes.get(NAME, select='Name,Parameters').parameters}
            assert parameters == {'pYear': ('String', '2024'), 'pScale': ('Numeric', 1000)}
    finally:
        tm1.processes.delete(NAME)


def test_rules_with_an_error_are_checked_and_the_error_is_on_its_line(tm1):
    cube = next(c for c in tm1.cubes.list(select='Name,Rules', expand='Dimensions($select=Name)') if c.rules)
    original = cube.rules
    text = rule_file.rules_to_text(cube.name, [d.name for d in cube.dimensions], original)
    broken = text.rstrip('\n') + "\n\n['no such element'] = N: undefined_function_xyz(1);\n"
    try:
        errors = put.put_rules(cube.name, broken)(tm1)
        assert errors and 'undefined_function_xyz' in broken.split('\n')[errors[0][0]]
    finally:
        from skipcheck_tm1.model import CubePatch
        tm1.cubes.update(cube.name, CubePatch.builder().rules(original).build())
    assert put.put_rules(cube.name, text)(tm1) == []
