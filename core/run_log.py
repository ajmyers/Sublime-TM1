"""Reading one process run's messages out of TM1's message log.

The message log's SessionID isn't the REST session's ID (they're numbered apart on TM1 11.8), so a
run is found by its thread: from its own "Process "X" executed by user" entry to its own "finished"
or "aborted" one. Threads are reused, so the entries before and after are left out.
"""

import re

ERROR_FILE = re.compile(r'tm1processerror\S*?\.log', re.IGNORECASE)


def run_messages(entries, process, user=None):
    """The entries of the process's latest run, in order. ``entries`` are MessageLogEntry, oldest
    first; ``user`` narrows it to runs by that user."""
    start_text = 'Process "{}" executed by user'.format(process)
    starts = [e for e in entries if e.message.startswith(start_text)
              and (user is None or '"{}"'.format(user).lower() in e.message.lower())]
    if not starts:
        return []
    start = starts[-1]
    run = []
    for entry in entries[entries.index(start):]:
        if entry.thread_id != start.thread_id:
            continue
        run.append(entry)
        if entry is not start and entry.message.startswith('Process "{}":'.format(process)):
            break
    return run


def error_files(messages):
    """The TM1ProcessError files the messages name."""
    found = []
    for entry in messages:
        for name in ERROR_FILE.findall(entry.message):
            if name not in found:
                found.append(name)
    return found


def callers_first(names):
    """Process names with the "callers" (a name with Call or Caller in it) first, as 0.2.x listed them."""
    callers = [n for n in names if re.search(r'(\.?)(Call(er)?)(\.?)', n, re.IGNORECASE)]
    return callers + [n for n in names if n not in callers]


def order(entry):
    """Log order: by time, then by the entry's ID, as entries of one millisecond come in any order."""
    try:
        ident = int(entry.id)
    except (TypeError, ValueError):
        ident = 0
    return (entry.time_stamp, ident)


def complete(messages, process):
    """Whether the run's messages run from its start to its end."""
    return len(messages) > 1 and messages[-1].message.startswith('Process "{}":'.format(process))
