"""Plain-text tables, for output panels."""


def table(columns, rows, border=False, max_width=200):
    """``rows`` laid out under ``columns``, each column as wide as its widest cell (to
    ``max_width``). With ``border``, framed in +---+ lines."""
    cells = [[str(c) for c in columns]] + [['' if v is None else str(v) for v in row] for row in rows]
    cells = [[c.replace('\n', ' ')[:max_width] for c in row] for row in cells]
    widths = [max(len(row[i]) for row in cells) for i in range(len(columns))]

    def line(row):
        text = (' | ' if border else '  ').join(c.ljust(w) for c, w in zip(row, widths))
        return ('| ' + text + ' |') if border else text.rstrip()

    if border:
        rule = '+' + '+'.join('-' * (w + 2) for w in widths) + '+'
        lines = [rule, line(cells[0]), rule] + [line(row) for row in cells[1:]] + [rule]
    else:
        lines = [line(cells[0]), '  '.join('-' * w for w in widths)] + [line(row) for row in cells[1:]]
    return '\n'.join(lines)
