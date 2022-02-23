import json
import os
import re
import subprocess
import traceback

import sublime
import sublime_plugin

from pelle.Utils import encode


class CreateNewTm1Project(sublime_plugin.TextCommand):

    def run(self, edit, confirm, **args):
        if confirm != 'Yes':
            return

        if args['is_cloud'] == 'Yes':
            args['port'] = '443/tm1/api/tm1'
            args['ssl'] = 'Yes'
            args['namespace'] = 'LDAP'

        try:
            project_path = os.path.join(args['project_path'], args['project_name'])
            os.mkdir(project_path)

            project = {
                'folders': [
                    {
                        'name': args['project_name'],
                        'path': project_path
                    }
                ],
                'settings': {
                    'tm1_connection': {
                        'address': args['address'],
                        'port': args['port'],
                        'user': args['user'],
                        'ssl': True if args['ssl'] == 'Yes' else False,
                        'password': encode(args['password']),
                        'namespace': args['namespace'],
                        'async_requests_mode': True
                    },
                    "format_process_on_update": True,
                }
            }

            project_file = os.path.join(project_path, args['project_name'] + '.sublime-project')
            with open(project_file, 'w') as f:
                f.write(json.dumps(project, indent=4))

            subl([project_file])


        except Exception as e:
            sublime.message_dialog('Project Creation failed with: {}'.format(e))
            traceback.print_exc()

    def input(self, args):
        if 'project_name' not in args or not re.match(r'^[\w\-. ]+$', args.get('project_name')):
            selected = args.get('project_name')
            return ProjectNameInputHandler(selected)

        if 'project_path' not in args or not os.path.exists(args['project_path']):
            selected = args.get('project_path')
            return ProjectPathInputHandler(selected)

        if 'is_cloud' not in args:
            return IsCloudInputHandler()

        is_cloud = True if args['is_cloud'] == 'Yes' else False

        if 'address' not in args:
            return AddressInputHandler(is_cloud)

        if not is_cloud:
            if 'port' not in args:
                return PortInputHandler()

            if 'ssl' not in args:
                return SslInputHandler()

        if 'user' not in args:
            return UserInputHandler(is_cloud)

        if 'password' not in args:
            return PasswordInputHandler()

        if not is_cloud:
            if 'namespace' not in args:
                return NamespaceInputHandler()

        if 'confirm' not in args:
            return ConfirmInputHandler(args)

    def input_description(self):
        return 'Create New TM1 Project'


class ProjectNameInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, selected):
        self.selected = selected

    def placeholder(self):
        return 'Input a project name. i.e netflix-dev'

    def preview(self, text):
        preview = self.placeholder()
        if self.selected:
            preview += '<br><br>ERROR: \'{}\' is not a valid project name'.format(self.selected)
        return sublime.Html(preview)

    def initial_text(self):
        return self.selected


class ProjectPathInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, selected):
        self.selected = selected

    def placeholder(self):
        if sublime.platform() == 'windows':
            location = r'C:\Users\andrewmyers\Desktop'
        else:
            location = r'/Users/andrewmyers/Desktop'
        return 'Input a project location. i.e ({})'.format(location)

    def preview(self, text):
        preview = self.placeholder()
        if self.selected:
            preview += '<br><br>ERROR: \'{}\' is not a valid path'.format(self.selected)
        return sublime.Html(preview)

    def initial_text(self):
        return self.selected


class IsCloudInputHandler(sublime_plugin.ListInputHandler):
    def list_items(self):
        return ['No', 'Yes']

    def placeholder(self):
        return 'Are you connecting to the IBM Cloud? (Yes or No)'

    def preview(self, text):
        return self.placeholder()


class AddressInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, is_cloud):
        self.is_cloud = is_cloud

    def placeholder(self):
        if self.is_cloud:
            server = 'mycompany.planning-analytics.ibmcloud.com'
        else:
            server = 'tm1server.corp.mycompany.net or 192.168.1.123'

        return 'Input the server name or ip address. i.e {}'.format(server)

    def preview(self, text):
        return self.placeholder()


class PortInputHandler(sublime_plugin.TextInputHandler):
    def placeholder(self):
        return 'Input the TM1 REST API port # (HTTPPortNumber in tm1s.cfg on TM1 server)'

    def preview(self, text):
        return self.placeholder()


class SslInputHandler(sublime_plugin.ListInputHandler):
    def list_items(self):
        return ['No', 'Yes']

    def placeholder(self):
        return 'Require SSL? (defined in UseSSL in tm1s.cfg on TM1 server)'

    def preview(self, text):
        return self.placeholder()


class UserInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, is_cloud):
        self.is_cloud = is_cloud

    def placeholder(self):
        if self.is_cloud:
            server = 'user01_tm1_automation'
        else:
            server = 'username'

        return 'Input your TM1 username. i.e {}'.format(server)

    def preview(self, text):
        preview = self.placeholder()
        if self.is_cloud:
            preview += '<br><br>Note: for IBM Cloud, this must be an automation user provided in the welcome pack. Your IBM ID will <b>NOT</b> work'
        return sublime.Html(preview)


class PasswordInputHandler(sublime_plugin.TextInputHandler):
    def placeholder(self):
        return 'Input your TM1 password. i.e mysecurepassword'

    def preview(self, text):
        return self.placeholder()


class NamespaceInputHandler(sublime_plugin.TextInputHandler):
    def placeholder(self):
        return 'Your user\'s CAM Namespace (leave blank for SecurityMode=1)'

    def preview(self, text):
        return self.placeholder()


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
        output += '<li><b>Project Path:</b> {}</li>'.format(
            os.path.join(self.args['project_path'], self.args['project_name']))

        output += '<li><b>Is IBM Cloud:</b> {}</li>'.format(self.args['is_cloud'])
        output += '<li><b>Server:</b> {}</li>'.format(self.args['address'])
        if self.args['is_cloud'] == 'No':
            output += '<li><b>Port:</b> {}</li>'.format(self.args['port'])
            output += '<li><b>Use SSL:</b> {}</li>'.format(self.args['ssl'])
        output += '<li><b>User:</b> {}</li>'.format(self.args['user'])
        output += '<li><b>Password:</b> {}</li>'.format(self.args['password'])
        if self.args['is_cloud'] == 'No':
            output += '<li><b>CAM Namespace:</b> {}</li>'.format(self.args['namespace'])

        output += '</ul>'

        return sublime.Html(output)


# Code lifted from https://github.com/randy3k/ProjectManager/blob/master/pm.py
def subl(args=[]):
    # learnt from SideBarEnhancements
    executable_path = sublime.executable_path()

    if sublime.platform() == 'linux':
        subprocess.Popen([executable_path] + [args])
    if sublime.platform() == 'osx':
        app_path = executable_path[:executable_path.rfind(".app/") + 5]
        executable_path = app_path + "Contents/SharedSupport/bin/subl"
        subprocess.Popen([executable_path] + args)
    if sublime.platform() == "windows":
        def fix_focus():
            window = sublime.active_window()
            view = window.active_view()
            window.run_command('focus_neighboring_group')
            window.focus_view(view)

        sublime.set_timeout(fix_focus, 300)
