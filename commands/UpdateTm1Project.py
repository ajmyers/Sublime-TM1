import traceback

import sublime
import sublime_plugin

from ..utils.Utils import encode


class UpdateTm1Project(sublime_plugin.TextCommand):

    def run(self, edit, confirm, **args):
        if confirm != 'Yes':
            return

        try:
            args['password'] = encode(args['password'])

            if not self.project_settings.get('settings'):
                self.project_settings['settings'] = {}

            if self.project_settings['settings'].get('TM1ConnectionSettings'):
                self.project_settings['settings'].pop('TM1ConnectionSettings')

            self.project_settings['settings']['tm1_connection'] = args

            sublime.active_window().set_project_data(self.project_settings)
        except Exception as e:
            sublime.message_dialog('Project Creation failed with: {}'.format(e))
            traceback.print_exc()

    def input(self, args):
        if not args:
            self.project_settings = sublime.active_window().project_data()

            if not self.project_settings:
                sublime.message_dialog(
                    'Current window is not a valid sublime project. Please use Create New TM1 Project')
                return

            self.plugin_settings = self.project_settings.get('settings', {})
            self.connection_settings = self.plugin_settings.get('tm1_connection')

            # Legacy
            if not self.connection_settings:
                self.connection_settings = self.plugin_settings.get('TM1ConnectionSettings')

                if self.connection_settings:
                    self.connection_settings = Utils.cleanup_old_settings(self.connection_settings)

        if not self.connection_settings:
            self.connection_settings = {}

        if 'address' not in args:
            selected = self.connection_settings.get('address')
            return AddressInputHandler(selected)

        if 'port' not in args:
            selected = self.connection_settings.get('port')
            return PortInputHandler(selected)

        if 'ssl' not in args:
            selected = 'Yes' if self.connection_settings.get('port') else None
            return SslInputHandler(selected)

        if 'user' not in args:
            selected = self.connection_settings.get('user')
            return UserInputHandler(selected)

        if 'password' not in args:
            return PasswordInputHandler()

        if 'namespace' not in args:
            selected = self.connection_settings.get('namespace')
            return NamespaceInputHandler(selected)

        if 'confirm' not in args:
            return ConfirmInputHandler(args)

    def input_description(self):
        return 'Update TM1 Project'


class AddressInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, selected):
        self.selected = selected

    def placeholder(self):
        server = 'tm1server.corp.mycompany.net or 192.168.1.123'

        return 'Input the server name or ip address. i.e {}'.format(server)

    def preview(self, text):
        return self.placeholder()

    def initial_text(self):
        return self.selected


class PortInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, selected):
        self.selected = selected

    def placeholder(self):
        return 'Input the TM1 REST API port # (HTTPPortNumber in tm1s.cfg on TM1 server)'

    def preview(self, text):
        return self.placeholder()

    def initial_text(self):
        return self.selected


class SslInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self, selected):
        self.selected = selected

    def list_items(self):
        return ['No', 'Yes']

    def placeholder(self):
        return 'Require SSL? (defined in UseSSL in tm1s.cfg on TM1 server)'

    def preview(self, text):
        return self.placeholder()

    def initial_text(self):
        return self.selected


class UserInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, selected):
        self.selected = selected

    def placeholder(self):
        server = 'username'

        return 'Input your TM1 username. i.e {}'.format(server)

    def preview(self, text):
        preview = self.placeholder()

        return sublime.Html(preview)

    def initial_text(self):
        return self.selected


class PasswordInputHandler(sublime_plugin.TextInputHandler):
    def placeholder(self):
        return 'Input your TM1 password. i.e mysecurepassword'

    def preview(self, text):
        return self.placeholder()


class NamespaceInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, selected):
        self.selected = selected

    def placeholder(self):
        return 'Your user\'s CAM Namespace (leave blank for SecurityMode=1)'

    def preview(self, text):
        return self.placeholder()

    def initial_text(self):
        return self.selected


class ConfirmInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self, args):
        self.args = args

    def list_items(self):
        return ['Yes', 'No']

    def placeholder(self):
        return 'Confirm correct settings'

    def preview(self, text):
        output = ''
        output += 'Please confirm settings are correct'
        output += '<ul>'
        output += '<li><b>Server:</b> {}</li>'.format(self.args['address'])
        output += '<li><b>Port:</b> {}</li>'.format(self.args['port'])
        output += '<li><b>Use SSL:</b> {}</li>'.format(self.args['ssl'])
        output += '<li><b>User:</b> {}</li>'.format(self.args['user'])
        output += '<li><b>Password:</b> {}</li>'.format(self.args['password'])
        output += '<li><b>CAM Namespace:</b> {}</li>'.format(self.args['namespace'])
        output += '</ul>'

        return sublime.Html(output)
