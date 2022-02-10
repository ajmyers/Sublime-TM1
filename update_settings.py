import base64
import sublime
import sublime_plugin


SESSION_DEFAULT = {
    'APIString': '/api/v1/',
    'CAMNamespaceID': '',
    'Password': '',
    'PortNumber': '',
    'ServerAddress': '',
    'UseSSL': 'F',
    'UserName': ''
    'UseAsync': 'F'
}


class UpdateTm1ProjectSettings(sublime_plugin.WindowCommand):
    def run(self):
        self.active_project = sublime.active_window().project_data()
        self.project_settings = self.active_project.get('settings', {})
        self.session_settings = self.project_settings.get('TM1ConnectionSettings', {})

        if not self.active_project:
            sublime.message_dialog("Active window is not currently configured as a project.\n\nPlease go to Project -> Save Project As to continue")
            return

        self.input_values, self.prompts, self.default_values = [], [], []
        self.counter = 0

        for key, setting in SESSION_DEFAULT.items():
            if key == 'Password':
                self.session_settings[key] = ''
            else:
                self.session_settings.setdefault(key, setting)

        for key, setting in self.session_settings.items():
            self.prompts.append(key)
            self.default_values.append(setting)

        self.show_prompt()

    def show_prompt(self):
        self.window.show_input_panel(self.prompts[self.counter], self.default_values[self.counter], self.on_done, None, None)

    def on_done(self, content):
        self.input_values.append(content)
        self.counter += 1
        if self.counter < len(self.prompts):
            self.show_prompt()
        else:
            self.input_done()

    def input_done(self):
        for counter in range(0, len(self.prompts)):
            self.session_settings[self.prompts[counter]] = self.input_values[counter]

        self.session_settings['Password'] = self.encode("1234567890", self.session_settings['Password'])
        self.active_project['settings'] = self.project_settings
        self.active_project['settings']['TM1ConnectionSettings'] = self.session_settings

        sublime.active_window().set_project_data(self.active_project)

    def encode(self, key, clear):
        enc = []
        for i in range(len(clear)):
            key_c = key[i % len(key)]
            enc_c = chr((ord(clear[i]) + ord(key_c)) % 256)
            enc.append(enc_c)
        return base64.urlsafe_b64encode("".join(enc).encode()).decode()
