"""Just enough of Sublime Text's `sublime` module to import and test the package outside Sublime."""

COMPLETION_FORMAT_TEXT = 0
DRAW_NO_FILL = 32
DRAW_NO_OUTLINE = 256
DRAW_SQUIGGLY_UNDERLINE = 1024
COMPLETION_FORMAT_SNIPPET = 1
KIND_SNIPPET = (5, 's', 'Snippet')

_platform = 'osx'
dialogs = []
statuses = []


def platform():
    return _platform


def version():
    return '4215'


def message_dialog(message):
    dialogs.append(message)


_ok_cancel_answers = []


def ok_cancel_dialog(message, ok_title=''):
    dialogs.append(message)
    return _ok_cancel_answers.pop(0) if _ok_cancel_answers else True


def error_message(message):
    dialogs.append(message)


def status_message(message):
    statuses.append(message)


def set_timeout(callback, delay=0):
    callback()


def set_timeout_async(callback, delay=0):
    callback()


def active_window():
    return None


_cache_path = '/tmp/sublime-cache'


def cache_path():
    return _cache_path


def executable_path():
    return '/Applications/Sublime Text.app/Contents/MacOS/sublime_text'


class Region:
    def __init__(self, a, b=None):
        self.a = a
        self.b = a if b is None else b

    def begin(self):
        return min(self.a, self.b)

    def end(self):
        return max(self.a, self.b)

    def __eq__(self, other):
        return isinstance(other, Region) and (self.a, self.b) == (other.a, other.b)

    def __repr__(self):
        return 'Region({}, {})'.format(self.a, self.b)


class Html:
    def __init__(self, text):
        self.text = text


class CompletionItem:
    def __init__(self, trigger, annotation='', completion='', completion_format=COMPLETION_FORMAT_TEXT,
                 kind=None, details=''):
        self.trigger = trigger
        self.annotation = annotation
        self.completion = completion
        self.completion_format = completion_format
        self.kind = kind
        self.details = details


class Settings(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value):
        self[key] = value


_settings = {}


def load_settings(name):
    return _settings.setdefault(name, Settings())


class QuickPanelItem:
    def __init__(self, trigger, details='', annotation='', kind=None):
        self.trigger, self.details, self.annotation, self.kind = trigger, details, annotation, kind
