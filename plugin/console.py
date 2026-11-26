"""The TM1 console: the server's threads (TM1Top), killing one, and following the message log.

Each panel refreshes on a timer on the UI thread while it's showing, and stops when it's hidden.
Every refresh is one request through the gateway, never two at once. 0.2.x ran a thread that called a
TextCommand every 2.5 seconds, and that command made the HTTP request on the UI thread.

skipcheck-tm1's tail_message_log isn't used for the log: it's an iterator that keeps polling
without yielding while the log is quiet (so a closed panel couldn't stop it, and it would hold one of
the gateway's threads), and on TM1 11.8 each of its polls returns everything since it started.
"""

import sublime
import sublime_plugin

from ..core import threads as tm1_threads
from . import gateway

CONSOLE = 'TM1 Console'
SERVER_LOG = 'TM1 Server Log'
DEFAULT_REFRESH = 2.5
LOG_REFRESH = 2.0
FIRST_LOG_LINES = 50

_running = {}


def refresh_seconds(window):
    settings = (window.project_data() or {}).get('settings', {})
    try:
        return max(0.5, float(settings.get('ConsoleRefreshTime', DEFAULT_REFRESH)))
    except (TypeError, ValueError):
        return DEFAULT_REFRESH


def panel(window, name):
    view = window.find_output_panel(name) or window.create_output_panel(name)
    view.settings().set('word_wrap', False)
    return view


def showing(window, name):
    return window.active_panel() == 'output.' + name


class Poller:
    """Runs ``fetch(client)`` through the gateway every ``seconds`` while the panel shows,
    handing each result to ``show``. One at a time, and none once the panel is hidden."""

    def __init__(self, window, name, fetch, show, seconds):
        self.window, self.name, self.fetch, self.show, self.seconds = window, name, fetch, show, seconds
        self.busy = False
        self.stopped = False
        # Until the first result, a hidden panel is the password prompt's doing (Sublime shows one
        # panel at a time), not the user's: it doesn't stop the poller, and the result shows it again
        self.shown = False

    def start(self):
        key = (self.window.id(), self.name)
        if key in _running:
            _running[key].stopped = True
        _running[key] = self
        self.tick()

    def tick(self):
        if self.stopped or (self.shown and not showing(self.window, self.name)):
            key = (self.window.id(), self.name)
            # Only its own entry: a poller replaced by a newer one mustn't unregister that one
            if _running.get(key) is self:
                del _running[key]
            return
        if not self.busy:
            tm1 = gateway.for_window(self.window, quiet=True)
            if tm1 is None:
                return
            self.busy = True
            tm1.run(self.window, self.fetch, self.done, self.failed, self.cancelled)
        sublime.set_timeout(self.tick, int(self.seconds * 1000))

    def done(self, result):
        self.busy = False
        if not self.stopped:
            if not self.shown:
                self.shown = True
                if not showing(self.window, self.name):
                    self.window.run_command('show_panel', {'panel': 'output.' + self.name})
            self.show(result)

    def cancelled(self):
        # Signing in was cancelled (Esc at the password prompt, say): nothing more will come, and
        # the panel the prompt replaced mustn't keep this poller ticking unseen
        self.busy = False
        self.stopped = True

    def failed(self, error):
        self.busy = False
        self.stopped = True
        view = panel(self.window, self.name)
        view.run_command('tm1_set_panel_text', {'text': 'TM1 stopped answering: {}\n'.format(error), 'append': True})


class DisplayTm1OpsConsole(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return bool(self.window.project_file_name())

    def run(self):
        if gateway.for_window(self.window) is None:
            return
        view = panel(self.window, CONSOLE)
        self.window.run_command('show_panel', {'panel': 'output.' + CONSOLE})

        def show(threads):
            view.run_command('tm1_set_panel_text', {'text': tm1_threads.thread_table(threads)})

        Poller(self.window, CONSOLE, lambda client: client.threads.list(), show, refresh_seconds(self.window)).start()


class RefreshTm1OpsConsoleCommand(sublime_plugin.WindowCommand):
    """0.2.x's refresh command, kept for keybindings: refreshes the console now."""

    def run(self):
        self.window.run_command('display_tm1_ops_console')


class KillTm1ThreadCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return bool(self.window.project_file_name())

    def run(self, thread=None):
        tm1 = gateway.for_window(self.window)
        if tm1 is None:
            return
        if thread is not None:
            self.kill(tm1, thread)
            return
        tm1.run(self.window, lambda client: tm1_threads.others(client.threads.list()),
                lambda threads: self.choose(tm1, threads))

    def choose(self, tm1, threads):
        if not threads:
            self.window.status_message('TM1: no other threads running')
            return
        items = [sublime.QuickPanelItem('{} {}'.format(t.id, tm1_threads.user_name(t.name)),
                                        details=[t.function or '', t.object_name or ''],
                                        annotation=str(getattr(t.state, 'value', t.state)))
                 for t in threads]

        def chosen(index):
            if index < 0:
                return
            thread = threads[index]

            def confirmed(answer):
                if answer == 0:
                    self.kill(tm1, thread.id)

            confirm = [sublime.QuickPanelItem('Cancel thread {}'.format(thread.id), details=[thread.function or '']),
                       sublime.QuickPanelItem('Leave it running')]
            self.window.show_quick_panel(confirm, confirmed, placeholder='Cancel this thread on TM1?')

        self.window.show_quick_panel(items, chosen, placeholder='Thread to cancel')

    def kill(self, tm1, thread):
        def done(_):
            self.window.status_message('TM1: asked thread {} to cancel'.format(thread))
            if showing(self.window, CONSOLE):
                self.window.run_command('display_tm1_ops_console')

        tm1.run(self.window, lambda client: client.threads.cancel(int(thread)), done)


class Tm1TailServerLogCommand(sublime_plugin.WindowCommand):
    """TM1: Console - Tail Server Log: the message log as it's written."""

    def is_enabled(self):
        return bool(self.window.project_file_name())

    def run(self):
        if gateway.for_window(self.window) is None:
            return
        view = panel(self.window, SERVER_LOG)
        self.window.run_command('show_panel', {'panel': 'output.' + SERVER_LOG})
        state = {'last': None}

        def fetch(client):
            if state['last'] is None:
                return list(reversed(client.logs.message_log_entries(orderby='TimeStamp desc', top=FIRST_LOG_LINES)))
            since = state['last'].isoformat().replace('+00:00', 'Z')
            return client.logs.message_log_entries(filter='TimeStamp gt {}'.format(since), orderby='TimeStamp asc',
                                                   top=1000)

        def show(entries):
            if entries:
                state['last'] = entries[-1].time_stamp
                text = '\n'.join(tm1_threads.log_lines(entries)) + '\n'
                view.run_command('tm1_set_panel_text', {'text': text, 'append': True})

        Poller(self.window, SERVER_LOG, fetch, show, LOG_REFRESH).start()


class Tm1SetPanelTextCommand(sublime_plugin.TextCommand):
    """Sets (or appends to) an output panel's text, keeping it read-only."""

    def run(self, edit, text, append=False):
        self.view.set_read_only(False)
        if append:
            self.view.insert(edit, self.view.size(), text)
            self.view.show(self.view.size())
        else:
            self.view.replace(edit, sublime.Region(0, self.view.size()), text)
        self.view.set_read_only(True)
