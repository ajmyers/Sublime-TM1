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

DIMENSION_ROW = '''
###     {index}: {dimension}
'''.strip('\n')
