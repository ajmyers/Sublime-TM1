"""Passwords, asked for when a project first connects and kept in memory, or, if the user chooses,
in the operating system's credential store (core/keychain.py).

0.2.x stored the password in the project file, obfuscated with a fixed key: as good as plain
text, in a file that's often shared or committed. Now it's asked once per Sublime session per
project, and forgotten when TM1 refuses it, when the user signs out, or when Sublime closes.

After TM1 first accepts a typed password, the user is offered to remember it in the store; the
answer is the project's "remember_password" under "tm1". A remembered password is used at the next
connection, and removed from the store when TM1 refuses it or the user signs out. The store is
keyed by the connection (namespace, user and server), not the project file. Any failure of the
store is printed and the password asked for as without one: it never blocks a connection.
"""

import threading

import sublime
import sublime_plugin

from ..core import keychain

MASK = '•'
REMEMBER = 'remember_password'

_passwords = {}


def _background(fn):
    """Runs fn off the UI thread: the store can be slow (secret-tool on Linux, a locked Keychain)."""
    threading.Thread(target=fn, name='tm1-keychain', daemon=True).start()

# Projects whose password was typed this session and not yet accepted by TM1
_typed = set()


def known(key):
    return key in _passwords


def forget(key, connection=None):
    """Forgets the project's password; with the connection, removes it from the store too."""
    _passwords.pop(key, None)
    _typed.discard(key)
    if connection is not None:
        name = account(connection)
        _background(lambda: keychain.delete(name))


def forget_all():
    _passwords.clear()
    _typed.clear()


def account(connection):
    """The store's name for a connection's password: who, and where."""
    return connection.describe()


def remembering(window):
    """The project's answer to remembering its password: True, False, or None (not asked, or a
    project with only 0.2.x's settings, which has nowhere to keep it)."""
    settings = ((window.project_data() or {}).get('settings') or {}).get('tm1')
    if not isinstance(settings, dict):
        return None
    value = settings.get(REMEMBER)
    return value if isinstance(value, bool) else None


def _save_answer(window, value):
    project = window.project_data() or {}
    settings = (project.get('settings') or {}).get('tm1')
    if isinstance(settings, dict):
        settings[REMEMBER] = value
        window.set_project_data(project)


def with_password(window, key, connection, then, on_cancel=None):
    """Calls then(password) on the UI thread: at once when the project's password is known (this
    session, or remembered in the store), or once the user has typed it."""
    if key in _passwords:
        then(_passwords[key])
        return

    def done(password):
        _passwords[key] = password
        _typed.add(key)
        then(password)

    def ask():
        ask_secret(window, 'TM1 password for {}:'.format(connection.describe()), done, on_cancel)

    if not remembering(window):
        ask()
        return

    def read():
        stored = keychain.get(account(connection))

        def back():
            if stored is None:
                ask()
            else:
                _passwords[key] = stored
                then(stored)
        sublime.set_timeout(back, 0)

    _background(read)


def accepted(window, key, connection):
    """TM1 took the project's password. A password typed this session is stored when the project
    remembers its password, or the user is offered to, once per project."""
    if key not in _typed or key not in _passwords:
        return
    _typed.discard(key)
    answer = remembering(window)
    if answer:
        password = _passwords[key]
        _background(lambda: keychain.store(account(connection), password))
    elif answer is None and keychain.available() and isinstance(
            ((window.project_data() or {}).get('settings') or {}).get('tm1'), dict):
        _offer(window, key, connection)


def _offer(window, key, connection):
    store = keychain.name()
    items = [sublime.QuickPanelItem('Remember the password in the {}'.format(store),
                                    details='For {}, until TM1 refuses it or you sign out'.format(
                                        connection.describe())),
             sublime.QuickPanelItem('Ask each session', details="Kept in memory only, as now")]

    def chosen(index):
        if index == 0:
            _save_answer(window, True)
            if key in _passwords:
                password = _passwords[key]

                def save():
                    if keychain.store(account(connection), password):
                        sublime.set_timeout(lambda: window.status_message(
                            'TM1: password remembered in the {}'.format(store)), 0)
                _background(save)
        elif index == 1:
            _save_answer(window, False)

    window.show_quick_panel(items, chosen, placeholder='TM1 accepted the password. Remember it?')


def rejected(key, connection):
    """TM1 refused the project's password: forgotten here and in the store, to be asked again."""
    forget(key, connection)


def unmask(secret, shown, mask=MASK):
    """The secret after an edit of the panel that shows it masked. Masked characters are the
    secret's, in order; any other character was just typed. Sublime's input panel can't mask, so
    the panel shows only masks and this keeps the text. A deletion is taken to be at the end, where
    the cursor is while typing a password."""
    kept = shown.count(mask)
    result, old = [], iter(secret[:kept])
    for char in shown:
        result.append(next(old, '') if char == mask else char)
    return ''.join(result)


def ask_secret(window, caption, on_done, on_cancel=None):
    """An input panel that shows each character typed as a bullet."""
    state = {'secret': '', 'panel': None}

    def changed(shown):
        secret = unmask(state['secret'], shown)
        state['secret'] = secret
        masked = MASK * len(secret)
        if shown != masked and state['panel'] is not None:
            state['panel'].run_command('tm1_replace_input_text', {'text': masked})

    def done(_shown):
        on_done(state['secret'])

    def cancelled():
        if on_cancel:
            on_cancel()

    panel = window.show_input_panel(caption, '', done, changed, cancelled)
    state['panel'] = panel
    if panel is not None:
        panel.settings().set('spell_check', False)
        panel.settings().set('auto_complete', False)
    return panel


class Tm1ReplaceInputTextCommand(sublime_plugin.TextCommand):
    """Replaces the text of the password panel with its masked form."""

    def run(self, edit, text):
        self.view.replace(edit, sublime.Region(0, self.view.size()), text)
        self.view.sel().clear()
        self.view.sel().add(sublime.Region(len(text)))
