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
        return SimpleNamespace(set=self._settings.__setitem__)

    def id(self):
        return id(self)

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

    def run(self, window, work, on_done=None, on_error=None, on_cancel=None):
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
    view = window.panel_views[console.CONSOLE]
    [phantom] = view.phantoms[console.CONSOLE]
    assert 'href="cancel:5"' in phantom.content and phantom.layout == sublime.LAYOUT_BLOCK
    assert view._settings['line_numbers'] is False and view._settings['gutter'] is False
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



class PasswordGateway(Gateway):
    """A gateway whose first run asks for the password, which shows the input panel in place of
    the console's (Sublime shows one panel at a time); the work runs once it's typed."""

    def __init__(self, client, window):
        super().__init__(client, defer=True)
        self.window = window

    def run(self, window, work, on_done=None, on_error=None, on_cancel=None):
        if self.calls == 0:
            self.window.active = 'input'
            self.cancel = on_cancel
        super().run(window, work, on_done, on_error)


def test_after_the_password_prompt_the_console_shows_and_keeps_polling(timers, monkeypatch):
    window = Window()
    gw = PasswordGateway(SimpleNamespace(threads=SimpleNamespace(list=lambda: [thread(5)])), window)
    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: gw)
    console.DisplayTm1OpsConsole(window).run()
    timers.pop(0)()                    # a tick while the password is being typed
    window.active = None               # typed: the input panel closes
    gw.pending.pop(0)()                # TM1 answers
    assert window.active == 'output.' + console.CONSOLE
    timers.pop(0)()
    assert gw.calls == 2               # still polling
    window.active = None               # now the user closes it
    timers.pop(0)()
    assert timers == [] and gw.calls == 2


def test_cancelling_the_password_prompt_stops_the_console(timers, monkeypatch):
    window = Window()
    gw = PasswordGateway(SimpleNamespace(threads=SimpleNamespace(list=lambda: [thread(5)])), window)
    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: gw)
    console.DisplayTm1OpsConsole(window).run()
    window.active = None               # Esc: the input panel closes, and no result will come
    gw.cancel()
    timers.pop(0)()
    assert timers == [] and (1, console.CONSOLE) not in console._running


def test_the_consoles_cancel_link_asks_before_cancelling(timers, monkeypatch):
    cancelled = []
    client = SimpleNamespace(threads=SimpleNamespace(list=lambda: [thread(5)], cancel=cancelled.append))
    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: Gateway(client))
    window = Window()
    commands = []
    window.run_command = lambda name, args=None: (
        commands.append((name, args)), Window.run_command(window, name, args))
    console.DisplayTm1OpsConsole(window).run()
    [phantom] = window.panel_views[console.CONSOLE].phantoms[console.CONSOLE]
    phantom.on_navigate('cancel:5')
    assert commands[-1] == ('kill_tm1_thread', {'thread': 5, 'confirm': True})
    kill = console.KillTm1ThreadCommand(window)
    kill.run(thread=5, confirm=True)
    assert cancelled == []
    window.quick_panels[-1]['on_select'](0)
    assert cancelled == [5]


def test_a_keybinding_with_only_a_thread_cancels_it_at_once(timers, monkeypatch):
    cancelled = []
    client = SimpleNamespace(threads=SimpleNamespace(list=lambda: [], cancel=cancelled.append))
    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: Gateway(client))
    console.KillTm1ThreadCommand(Window()).run(thread='7')
    assert cancelled == [7]


def test_a_refresh_clears_an_earlier_error_and_keeps_one_phantom(timers, monkeypatch):
    gw = Gateway(SimpleNamespace(threads=SimpleNamespace(list=lambda: [thread(5)])))
    monkeypatch.setattr(gateway, 'for_window', lambda w, quiet=False: gw)
    window = Window()
    console.DisplayTm1OpsConsole(window).run()
    timers.pop(0)()
    view = window.panel_views[console.CONSOLE]
    assert view.texts[-1] == {'text': ''} and len(view.phantoms[console.CONSOLE]) == 1
