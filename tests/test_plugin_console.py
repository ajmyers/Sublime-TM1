"""The console: polling while showing, one request at a time; killing a thread; the log tail."""

from types import SimpleNamespace

import pytest
import sublime

from fakes import FakeWindow
from tm1pkg.plugin import console, gateway


class Panel:
    def __init__(self):
        self.texts, self._settings = [], {}

    def settings(self):
        return SimpleNamespace(set=lambda k, v: None)

    def run_command(self, name, args):
        assert name == 'tm1_set_panel_text'
        self.texts.append(args)


class Window(FakeWindow):
    def __init__(self):
        super().__init__(project={'settings': {'ConsoleRefreshTime': 1}}, project_file='/p/x.sublime-project')
        self.panel_views, self.active = {}, None

    def id(self):
        return 1

    def find_output_panel(self, name):
        return self.panel_views.get(name)

    def create_output_panel(self, name):
        self.panel_views[name] = Panel()
        return self.panel_views[name]

    def run_command(self, name, args=None):
        if name == 'show_panel':
            self.active = args['panel']

    def active_panel(self):
        return self.active


class Gateway:
    def __init__(self, client, defer=False):
        self.client, self.defer, self.pending, self.calls = client, defer, [], 0

    def run(self, window, work, on_done=None, on_error=None):
        self.calls += 1
        step = lambda: on_done(work(self.client))  # noqa: E731
        self.pending.append(step) if self.defer else step()


@pytest.fixture
def timers(monkeypatch):
    queued = []
    monkeypatch.setattr(sublime, 'set_timeout', lambda fn, ms=0: queued.append(fn))
    console._running.clear()
    return queued


def thread(ident, function='GET /api/v1/Cubes'):
    return SimpleNamespace(id=ident, type='User', name='Admin', state='Run', function=function, object_name='',
                           r_locks=0, ix_locks=0, w_locks=0, elapsed_time='', wait_time='', info='')


def test_refreshes_while_showing_and_stops_when_hidden(timers, monkeypatch):
    gw = Gateway(SimpleNamespace(threads=SimpleNamespace(list=lambda: [thread(5)])))
    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: gw)
    window = Window()
    console.DisplayTm1OpsConsole(window).run()
    assert '| 5 ' in window.panel_views[console.CONSOLE].texts[-1]['text']
    timers.pop(0)()
    assert gw.calls == 2
    window.active = None  # the user closes the panel
    timers.pop(0)()
    assert gw.calls == 2 and timers == []


def test_never_sends_a_second_request_before_the_first_answers(timers, monkeypatch):
    gw = Gateway(SimpleNamespace(threads=SimpleNamespace(list=lambda: [])), defer=True)
    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: gw)
    console.DisplayTm1OpsConsole(Window()).run()
    timers.pop(0)()
    timers.pop(0)()
    assert gw.calls == 1


def test_killing_lists_other_threads_confirms_and_cancels(timers, monkeypatch):
    cancelled = []
    client = SimpleNamespace(threads=SimpleNamespace(list=lambda: [thread(5), thread(9, 'GET /api/v1/Threads')],
                                                     cancel=cancelled.append))
    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: Gateway(client))
    window = Window()
    console.KillTm1ThreadCommand(window).run()
    assert [i.trigger for i in window.quick_panels[0]['items']] == ['5 Admin']
    window.quick_panels[0]['on_select'](0)
    window.quick_panels[1]['on_select'](1)  # leave it running
    assert cancelled == []
    window.quick_panels[0]['on_select'](0)
    window.quick_panels[2]['on_select'](0)
    assert cancelled == [5]


def test_the_tail_starts_with_the_latest_lines_then_asks_only_for_newer_ones(timers, monkeypatch):
    asked = []

    def entries(**query):
        asked.append(query)
        stamp = SimpleNamespace(isoformat=lambda: '2026-11-23T21:00:00+00:00')
        return [SimpleNamespace(time_stamp=stamp, level='Info', logger='TM1', message='m{}'.format(len(asked)))]

    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: Gateway(
        SimpleNamespace(logs=SimpleNamespace(message_log_entries=entries))))
    window = Window()
    console.Tm1TailServerLogCommand(window).run()
    timers.pop(0)()
    assert asked[0] == {'orderby': 'TimeStamp desc', 'top': console.FIRST_LOG_LINES}
    assert asked[1]['filter'] == 'TimeStamp gt 2026-11-23T21:00:00Z'
    assert [t['append'] for t in window.panel_views[console.SERVER_LOG].texts] == [True, True]


def test_a_replaced_poller_doesnt_unregister_its_replacement(timers, monkeypatch):
    # Show Console run again (a refresh, or Kill Thread's) while the first poller still has a tick
    # pending: that tick must not unregister the second, or a third would leave the second polling
    gw = Gateway(SimpleNamespace(threads=SimpleNamespace(list=lambda: [])))
    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: gw)
    window = Window()
    console.DisplayTm1OpsConsole(window).run()   # poller A, with a tick pending
    console.DisplayTm1OpsConsole(window).run()   # poller B replaces A
    first_tick_of_a = timers.pop(0)
    first_tick_of_a()                            # A notices it was replaced
    console.DisplayTm1OpsConsole(window).run()   # poller C replaces B
    c = console._running[(1, console.CONSOLE)]
    calls = gw.calls
    pending, timers[:] = timers[:], []
    for tick in pending:                         # one round: B's tick and C's
        tick()
    # Only C still polls: B was stopped, so one request this round, not two
    assert gw.calls - calls == 1
    assert console._running[(1, console.CONSOLE)] is c
