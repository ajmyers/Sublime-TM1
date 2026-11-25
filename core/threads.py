"""TM1's threads, as the console shows them (TM1Top's columns), and the log tail's lines.

The console is minihtml in a phantom. minihtml has no <table> and no width, so columns line up by
padding each cell to its column's width, kept as written by white-space: pre, in the panel's
monospace font.
"""

import html
import re

COLUMNS = ['ID', 'Type', 'Name', 'State', 'Function', 'ObjectName', 'RLocks', 'IXLocks', 'WLocks',
           'ElapsedTime', 'WaitTime', 'Info']
# The console's own request for the threads
OWN_REQUEST = re.compile(r'/api/v1/Threads', re.IGNORECASE)


def user_name(name):
    """The user without the CAMID TM1 appends for CAM users, as 0.2.x showed it."""
    parts = (name or '').split(' ')
    return ' '.join(parts[:-1]) if len(parts) > 1 and parts[-1].startswith('CAMID') else (name or '')


def others(threads):
    """The threads, without the console's own request."""
    return [t for t in threads if not OWN_REQUEST.search(t.function or '')]


def _value(value):
    return getattr(value, 'value', value)


def rows(threads):
    return [[t.id, _value(t.type), user_name(t.name), _value(t.state), t.function, t.object_name, t.r_locks,
             t.ix_locks, t.w_locks, t.elapsed_time, t.wait_time, t.info] for t in others(threads)]


CANCEL = 'cancel:'
MAX_CELL = 60
# A state's colour, from the colour scheme's own, so it reads in light and dark schemes
STATE_COLOURS = {'run': 'var(--greenish)', 'wait': 'var(--yellowish)', 'commit': 'var(--bluish)',
                 'rollback': 'var(--redish)'}

STYLE = '''
body { margin: 0; padding: 0.3rem 0.5rem; }
.cell { white-space: pre; }
.row { padding: 0.1rem 0.3rem; }
.head { font-weight: bold; border-bottom: 1px solid color(var(--foreground) alpha(0.3)); }
.odd { background-color: color(var(--foreground) alpha(0.06)); }
a { text-decoration: none; color: var(--redish); }
.none { color: color(var(--foreground) alpha(0.6)); padding: 0.3rem; }
'''


def _cell(value):
    text = '' if value is None else str(value).replace('\n', ' ')
    return text if len(text) <= MAX_CELL else text[:MAX_CELL - 1] + '…'


def thread_html(threads):
    """The console's minihtml: a header row, then a row per thread (without the console's own
    request), each with a link to cancel:<id>."""
    table = [[_cell(v) for v in row] for row in rows(threads)]
    body = '<body id="tm1-console"><style>{}</style>'.format(STYLE)
    if not table:
        return body + '<div class="none">No other threads running.</div></body>'
    widths = [max(len(row[i]) for row in [COLUMNS] + table) for i in range(len(COLUMNS))]
    state_column = COLUMNS.index('State')

    def cells(row, coloured=False):
        out = []
        for i, (text, width) in enumerate(zip(row, widths)):
            padded = html.escape(text.ljust(width) + '  ')
            colour = STATE_COLOURS.get(text.lower()) if coloured and i == state_column else None
            out.append('<span style="color: {}">{}</span>'.format(colour, padded) if colour else padded)
        return '<span class="cell">{}</span>'.format(''.join(out))

    lines = ['<div class="row head">{}</div>'.format(cells(COLUMNS))]
    for index, row in enumerate(table):
        lines.append('<div class="row{}">{}<a href="{}{}">cancel</a></div>'.format(
            ' odd' if index % 2 else '', cells(row, coloured=True), CANCEL, html.escape(row[0])))
    return body + ''.join(lines) + '</body>'


def cancel_target(href):
    """The thread ID a link in the console's HTML is for, or None."""
    ident = href[len(CANCEL):] if href.startswith(CANCEL) else ''
    return int(ident) if ident.isdigit() else None


def log_lines(entries):
    """Message-log entries as the tail shows them, one per line."""
    return ['{}  {:<5}  {:<18}  {}'.format(str(e.time_stamp)[:23], str(_value(e.level))[:5], e.logger, e.message)
            for e in entries]
