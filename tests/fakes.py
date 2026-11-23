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
        getattr(self, 'regions', {}).pop(key, None)

    def is_dirty(self):
        return getattr(self, 'dirty', False)

    def text_point(self, row, col):
        lines = self.text.split('\n')
        return sum(len(line) + 1 for line in lines[:row]) + col

    def line(self, point):
        import sublime

        start = self.text.rfind('\n', 0, point) + 1
        end = self.text.find('\n', point)
        return sublime.Region(start, len(self.text) if end < 0 else end)

    def add_regions(self, key, regions, scope='', flags=0, annotations=None, annotation_color=''):
        self.regions = getattr(self, 'regions', {})
        self.regions[key] = {'regions': regions, 'annotations': annotations or []}

    def show_at_center(self, region):
        self.shown = region

    def region_text(self, key):
        return [self.substr(r) for r in self.regions[key]['regions']]

    def run_command(self, name, args=None):
        self.commands.append(name)


class FakeSettings(dict):
    def set(self, key, value):
        self[key] = value


class FakePanel:
    """An input panel: type() and submit() drive its callbacks; replace commands update its text."""

    def __init__(self, caption, on_done, on_change, on_cancel, initial=''):
        self.caption, self.text = caption, initial or ''
        self._on_done, self._on_change, self._on_cancel = on_done, on_change, on_cancel
        self._settings = FakeSettings()

    def settings(self):
        return self._settings

    def _changed(self):
        if self._on_change:
            self._on_change(self.text)

    def run_command(self, name, args=None):
        assert name == 'tm1_replace_input_text'
        self.text = args['text']
        self._changed()

    def type(self, chars):
        for char in chars:
            self.text += char
            self._changed()

    def backspace(self):
        self.text = self.text[:-1]
        self._changed()

    def submit(self):
        self._on_done(self.text)

    def cancel(self):
        if self._on_cancel:
            self._on_cancel()


class FakeWindow:
    def __init__(self, project=None, project_file=None):
        self.project = project
        self._project_file = project_file
        self.panels = []
        self.statuses = []
        self.quick_panels = []

    def status_message(self, text):
        self.statuses.append(text)

    def project_data(self):
        return self.project

    def set_project_data(self, data):
        self.project = data

    def project_file_name(self):
        return self._project_file

    def show_quick_panel(self, items, on_select, flags=0, selected_index=-1, on_highlight=None, placeholder=''):
        self.quick_panels.append({'items': items, 'on_select': on_select, 'placeholder': placeholder,
                                  'selected_index': selected_index})

    def find_output_panel(self, name):
        return getattr(self, 'outputs', {}).get(name)

    def create_output_panel(self, name):
        self.outputs = getattr(self, 'outputs', {})
        self.outputs[name] = FakeOutput()
        return self.outputs[name]

    def run_command(self, name, args=None):
        self.commands = getattr(self, 'commands', [])
        self.commands.append((name, args))

    def active_view(self):
        return getattr(self, 'view', None)

    def show_input_panel(self, caption, initial, on_done, on_change, on_cancel):
        panel = FakePanel(caption, on_done, on_change, on_cancel, initial)
        self.panels.append(panel)
        return panel


class FakeOutput:
    """An output panel: what's appended to it."""

    def __init__(self):
        self.text = ''

    def size(self):
        return len(self.text)

    def run_command(self, name, args=None):
        assert name == 'append'
        self.text += args['characters']
