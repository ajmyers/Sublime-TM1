"""Passwords, asked for when a project first connects and kept only in memory.

0.2.x stored the password in the project file, obfuscated with a fixed key: as good as plain
text, in a file that's often shared or committed. Now it's asked once per Sublime session per
project, and forgotten when TM1 refuses it, when the user signs out, or when Sublime closes.
"""

import sublime
import sublime_plugin

MASK = '•'

_passwords = {}


def known(key):
    return key in _passwords


def forget(key):
    _passwords.pop(key, None)


def forget_all():
    _passwords.clear()


def with_password(window, key, connection, then, on_cancel=None):
    """Calls ``then(password)`` on the UI thread: at once when the project's password is known,
    or once the user has typed it."""
    if key in _passwords:
        then(_passwords[key])
        return

    def done(password):
        _passwords[key] = password
        then(password)

    ask_secret(window, 'TM1 password for {}:'.format(connection.describe()), done, on_cancel)


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
