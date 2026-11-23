"""Stand-ins for Sublime's View and Window."""


class FakeView:
    def __init__(self, text='', file_name=None, window=None, scope=''):
        self.text = text
        self._file_name = file_name
        self._window = window
        self.scope = scope
        self.erased = []
        self.commands = []

    def file_name(self):
        return self._file_name

    def window(self):
        return self._window

    def size(self):
        return len(self.text)

    def substr(self, region):
        return self.text[region.begin():region.end()]

    def match_selector(self, point, selector):
        return all(part.strip() in self.scope for part in selector.split(','))

    def erase_regions(self, key):
        self.erased.append(key)

    def run_command(self, name, args=None):
        self.commands.append(name)


class FakeSettings(dict):
    def set(self, key, value):
        self[key] = value


class FakePanel:
    """An input panel: type() and submit() drive its callbacks; replace commands update its text."""

    def __init__(self, caption, on_done, on_change, on_cancel):
        self.caption, self.text = caption, ''
        self._on_done, self._on_change, self._on_cancel = on_done, on_change, on_cancel
        self._settings = FakeSettings()

    def settings(self):
        return self._settings

    def run_command(self, name, args=None):
        assert name == 'tm1_replace_input_text'
        self.text = args['text']
        self._on_change(self.text)

    def type(self, chars):
        for char in chars:
            self.text += char
            self._on_change(self.text)

    def backspace(self):
        self.text = self.text[:-1]
        self._on_change(self.text)

    def submit(self):
        self._on_done(self.text)

    def cancel(self):
        self._on_cancel()


class FakeWindow:
    def __init__(self, project=None, project_file=None):
        self.project = project
        self._project_file = project_file
        self.panels = []
        self.statuses = []

    def status_message(self, text):
        self.statuses.append(text)

    def project_data(self):
        return self.project

    def set_project_data(self, data):
        self.project = data

    def project_file_name(self):
        return self._project_file

    def show_input_panel(self, caption, initial, on_done, on_change, on_cancel):
        panel = FakePanel(caption, on_done, on_change, on_cancel)
        self.panels.append(panel)
        return panel
