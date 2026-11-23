"""Stand-ins for Sublime's View, for the code that reads a buffer."""


class FakeView:
    def __init__(self, text, file_name):
        self.text = text
        self._file_name = file_name

    def file_name(self):
        return self._file_name

    def size(self):
        return len(self.text)

    def substr(self, region):
        return self.text[region.begin():region.end()]
