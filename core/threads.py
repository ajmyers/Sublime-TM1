"""TM1's threads, as the console shows them (TM1Top's columns)."""

import re

from .table import table

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


def thread_table(threads):
    return table(COLUMNS, rows(threads), border=True, max_width=120)


def log_lines(entries):
    """Message-log entries as the tail shows them, one per line."""
    return ['{}  {:<5}  {:<18}  {}'.format(str(e.time_stamp)[:23], str(_value(e.level))[:5], e.logger, e.message)
            for e in entries]
