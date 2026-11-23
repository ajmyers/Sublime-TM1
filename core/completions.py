"""Completions generated from a TM1 model by Get: DB() for each cube in rules, and in processes
CELLGETN() and its kin for each cube, a locals block for each cube, and EXECUTEPROCESS() for each
process. They're the snippets the earlier version generated, character for character.

A completion here is a dict of sublime.CompletionItem's arguments, with "snippet" for the format and
the kind: the plugin turns them into CompletionItems (core/ doesn't import sublime).
"""

import re

RULE = 'source.tm1.rule'
TI = 'source.tm1.ti'

CUBE_FUNCTIONS = ['CELLGETN', 'CELLPUTN', 'CELLINCREMENTN', 'CELLGETS', 'CELLPUTS']
GENERATED = 'Auto-generated '
SANDBOXES = 'Sandboxes'


def build(cubes, processes):
    """The completions for a model, by selector. ``cubes`` are (name, dimension names) pairs;
    ``processes`` are skipcheck_tm1.model.Process."""
    ti = [execute_process(p) for p in processes]
    for function in CUBE_FUNCTIONS:
        ti += [cube_function(name, dimensions, function) for name, dimensions in cubes]
    ti += [cube_locals(name, dimensions) for name, dimensions in cubes]
    return {RULE: [db(name, dimensions) for name, dimensions in cubes], TI: ti}


def _completion(trigger, annotation, completion, details):
    return {'trigger': trigger, 'annotation': annotation, 'completion': completion,
            'completion_format': 'snippet', 'kind': 'snippet', 'details': details}


def _dimensions(dimensions):
    return [d for d in dimensions if d != SANDBOXES]


def _variable(dimension):
    name = dimension.replace(' ', '').replace('}', '').replace('_', '')
    match = re.search(r'([A-Z0-9])(.*?)($)', name)
    return match.group(0) if match else name


def _escaped(name):
    # A snippet treats a } as the end of a field
    return '\\' + name if name.startswith('}') else name


def execute_process(process):
    name = process.name
    parameters = process.parameters or []
    if not parameters:
        lines = ["EXECUTEPROCESS('{}');".format(name)]
    else:
        lines = ["EXECUTEPROCESS('{}'".format(name)]
        for index, parameter in enumerate(parameters, start=1):
            value = parameter.value
            if isinstance(value, str):
                lines.append("   , '%s', ${%s:'%s'}" % (parameter.name, index, value))
            else:
                lines.append("   , '%s', ${%s:%s}" % (parameter.name, index, value))
        lines.append(');')
    return _completion('EXECUTEPROCESS-{}'.format(name), "EXECUTEPROCESS('{}', ...)".format(name), '\n'.join(lines),
                       GENERATED + 'EXECUTEPROCESS() for ' + name)


def cube_function(cube, dimensions, function):
    start, fields = 1, []
    if 'PUTN' in function or 'INCREMENTN' in function:
        fields.append('${%s:nValue}' % start)
        start += 1
    elif 'PUTS' in function:
        fields.append('${%s:sValue}' % start)
        start += 1
    fields.append("${%s:'%s'}" % (start, _escaped(cube)))
    start += 1
    for index, dimension in enumerate(_dimensions(dimensions), start=start):
        fields.append('${%s:s%s_l}' % (index, _variable(dimension)))
    return _completion('{}-{}'.format(function, cube), "{}('{}', ...)".format(function, cube),
                       '{}('.format(function) + ', '.join(fields) + ');',
                       GENERATED + '{}() for {}'.format(function, cube))


LOCAL = r'${%s:%s}_l = ${%s/(^s.*?$)|(^n.*?$)/(?1:TRIM\(V%s\))(?2:NUMBR\(V%s\))/};'


def cube_locals(cube, dimensions):
    rule = '# ' + '=' * 68 + ' #'
    lines = [rule, '# Locals -- ' + cube, rule, '']
    index = 0
    for index, dimension in enumerate(_dimensions(dimensions), start=1):
        lines.append(LOCAL % (index, 's' + _variable(dimension), index, index, index))
    index += 1
    lines.append(LOCAL % (index, 'nValue', index, index, index))
    lines.append('')
    return _completion('_LOCALS-{}'.format(cube), cube, '\n'.join(lines), GENERATED + 'locals for cube {}'.format(cube))


def db(cube, dimensions):
    fields = ['${%s:!%s}' % (index, _escaped(dimension.replace(' ', '')))
              for index, dimension in enumerate(_dimensions(dimensions), start=1)]
    trigger = cube.replace(' ', '_').replace('.', '-').replace('}', '')
    completion = "DB('{}', ".format(cube) + ', '.join(fields) + ')'
    annotation = "DB('{}', ...)".format(cube)
    return _completion('DB-{}'.format(trigger), annotation, completion, GENERATED + 'DB() for ' + cube)


def is_generated(completion):
    """Whether a completion is one Get generated (here, or in the earlier version), rather than one
    a user wrote into the project."""
    return isinstance(completion, dict) and str(completion.get('details', '')).startswith(GENERATED)
