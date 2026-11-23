"""Stand-ins for Sublime's View and Window."""


class FakeView:
    def __init__(self, text='', file_name=None, window=None):
        self.text = text
        self._file_name = file_name
        self._window = window
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

    def erase_regions(self, key):
        self.erased.append(key)

    def run_command(self, name, args=None):
        self.commands.append(name)


class FakeWindow:
    def __init__(self, project=None):
        self.project = project

    def project_data(self):
        return self.project

    def set_project_data(self, data):
        self.project = data
