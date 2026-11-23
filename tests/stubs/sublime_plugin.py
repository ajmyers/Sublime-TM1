"""Just enough of Sublime Text's `sublime_plugin` module to import the package outside Sublime."""


class Command:
    def __init__(self, *args):
        pass


class ApplicationCommand(Command):
    pass


class WindowCommand(Command):
    def __init__(self, window=None):
        self.window = window


class TextCommand(Command):
    def __init__(self, view=None):
        self.view = view


class EventListener:
    pass


class ViewEventListener:
    def __init__(self, view=None):
        self.view = view


class TextInputHandler:
    pass


class ListInputHandler:
    pass
