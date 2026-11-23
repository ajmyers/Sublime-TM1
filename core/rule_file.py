"""The .rux file: a cube's rules, under a header naming the cube and its dimensions.

Put sends the whole file, header included, as the cube's rules; the header is all comments, so
TM1 ignores it. Get takes it off again before writing a fresh one, so it never doubles.
"""

TEMPLATE = '''
{header}

{body}
'''.lstrip('\n')

HEADER = '''
###############################################################################
### Cube: {cube}
### Dimensions:
{dimensions}
###############################################################################
'''.strip('\n')

DIMENSION_ROW = '###     {index}: {dimension}'

# A dimension TM1 adds to every cube; rules never address it
SANDBOXES = 'Sandboxes'


def header(cube_name, dimension_names):
    dimensions = [d for d in dimension_names if d != SANDBOXES]
    rows = '\n'.join(DIMENSION_ROW.format(index=i, dimension=d) for i, d in enumerate(dimensions, start=1))
    return HEADER.format(cube=cube_name, dimensions=rows)


def rules_to_text(cube_name, dimension_names, rules):
    """The .rux file for a cube's rules."""
    head = header(cube_name, dimension_names)
    body = (rules or '').replace(head, '').strip('\n')
    return TEMPLATE.format(header=head, body=body)


def text_to_rules(text):
    """The rules to put for a .rux file: the whole file, header included."""
    return text.replace('\r\n', '\n').strip('\n') + '\n'
