"""Setting up a project's connection from the TM1 server's host alone, and signing out.

TM1: Config - Create New TM1 Project and Update Current TM1 Project ask for the host (or a URL) and
work out the rest by asking the servers, without logging in (#40): the port and SSL from the Admin
Server, HTTPS or HTTP by trying, the login from TM1's 401, Cognos's namespaces and how each logs on.
Only what can't be found is asked for. No password is asked for or stored: the first connection
asks (#20).
"""

import json
import os
import shutil
import subprocess

import sublime
import sublime_plugin

from ..core import connection as connections
from ..core import discovery
from ..core.setup import parse_server, project_settings
from . import browser_sign_in, credentials, gateway


class Setup:
    """The steps, each asking the user or a server, ending in ``done(settings)``."""

    def __init__(self, window, done, initial=''):
        self.window, self.done, self.initial = window, done, initial
        self.host = self.port = self.ssl = None
        self.verify = True

    def start(self):
        self.window.show_input_panel('TM1 server (host name, or a URL):', self.initial, self.got_server, None, None)

    def background(self, work, then, message):
        self.window.status_message('TM1: ' + message)
        gateway.in_background(work, then, self.failed)

    def failed(self, error):
        sublime.error_message('TM1: setting up the connection stopped:\n\n{}'.format(error))

    def got_server(self, text):
        self.host, self.port, self.ssl = parse_server(text)
        if not self.host:
            return
        if self.port:
            self.probe()
        else:
            self.background(lambda: discovery.admin_servers(self.host), self.got_servers,
                            'asking the Admin Server on {} for its TM1 servers...'.format(self.host))

    def got_servers(self, servers):
        if not servers:
            self.window.show_input_panel('No TM1 Admin Server answered on {}. TM1 REST API port:'.format(self.host),
                                         '8010', self.got_port, None, None)
            return
        items = [sublime.QuickPanelItem(s.name, annotation='port {}{}'.format(s.port, ', HTTPS' if s.ssl else ''))
                 for s in servers]

        def chosen(index):
            if index >= 0:
                self.port = str(servers[index].port)
                self.probe()

        self.window.show_quick_panel(items, chosen, placeholder='TM1 server on {}'.format(self.host))

    def got_port(self, text):
        self.port = text.strip()
        if self.port:
            self.probe()

    def probe(self):
        self.background(lambda: discovery.probe_scheme(self.host, self.port.split('/')[0]), self.got_scheme,
                        'trying HTTPS, then HTTP, on {}:{}...'.format(self.host, self.port))

    def got_scheme(self, scheme):
        self.ssl = scheme.ssl
        if not scheme.trusted:
            trust = sublime.ok_cancel_dialog(
                "TM1 at {}:{} uses HTTPS, but its certificate isn't trusted on this computer (often IBM's "
                'self-signed one). Connect without checking it?\n\nTo check it instead, set "verify" under '
                '"tm1" in the project settings to a CA bundle that signs it.'.format(self.host, self.port),
                'Connect without checking')
            if not trust:
                return
            self.verify = False
        base = connections.Connection(address=self.host, port=self.port, user='', ssl=self.ssl, verify=self.verify)
        self.background(lambda: discovery.challenge(base.base_url, self.verify), self.got_challenge,
                        'asking TM1 how to log in...')

    def got_challenge(self, challenge):
        if challenge.kind == 'basic':
            self.ask_user('', 'basic')
        else:
            self.list_namespaces(challenge.dispatcher)

    def list_namespaces(self, dispatcher, override=''):
        def unreachable(error):
            self.window.show_input_panel(
                "Cognos isn't reachable at {} (TM1's ClientCAMURI). Cognos's address from here:".format(dispatcher),
                dispatcher, lambda text: self.list_namespaces(text.strip(), override=text.strip()), None, None)

        def got(namespaces):
            if len(namespaces) == 1:
                self.got_namespace(dispatcher, override, namespaces[0])
                return

            def chosen(index):
                if index >= 0:
                    self.got_namespace(dispatcher, override, namespaces[index])

            self.window.show_quick_panel(namespaces, chosen, placeholder='CAM namespace')

        self.window.status_message('TM1: asking Cognos for its namespaces...')
        gateway.in_background(lambda: discovery.namespaces(dispatcher, self.verify), got, unreachable)

    def got_namespace(self, dispatcher, override, namespace):
        def got(kind):
            if kind == 'browser':
                self.finish('', namespace, 'browser', override)
            else:
                self.ask_user(namespace, 'cam', override)

        self.background(lambda: discovery.login_kind(dispatcher, namespace, self.verify), got,
                        'asking Cognos how {} logs on...'.format(namespace))

    def ask_user(self, namespace, auth, override=''):
        caption = 'TM1 user{}:'.format(' in {}'.format(namespace) if namespace else '')
        self.window.show_input_panel(caption, '', lambda user: self.finish(user.strip(), namespace, auth, override),
                                     None, None)

    def finish(self, user, namespace, auth, dispatcher=''):
        self.done(project_settings(self.host, self.port, self.ssl, self.verify, user, namespace, auth, dispatcher))


def open_project(project_file):
    """Opens a project file in a new window (the subl command line, as 0.2.x did)."""
    executable = sublime.executable_path()
    platform = sublime.platform()
    if platform == 'osx':
        subl = executable[:executable.rfind('.app/') + 5] + 'Contents/SharedSupport/bin/subl'
    elif platform == 'windows':
        subl = os.path.join(os.path.dirname(executable), 'subl.exe')
    else:
        subl = executable
    subprocess.Popen([subl, '--project', project_file])


class CreateNewTm1Project(sublime_plugin.WindowCommand):
    def run(self):
        Setup(self.window, self.named).start()

    def named(self, settings):
        default = settings['address'].split('.')[0]
        self.window.show_input_panel('Project name:', default, lambda name: self.located(settings, name.strip()),
                                     None, None)

    def located(self, settings, name):
        if not name:
            return
        default = os.path.join(os.path.expanduser('~'), 'tm1-projects', name)
        self.window.show_input_panel('Project folder (the rules and processes go here):', default,
                                     lambda folder: self.create(settings, name, os.path.expanduser(folder.strip())),
                                     None, None)

    def create(self, settings, name, folder):
        os.makedirs(folder, exist_ok=True)
        project_file = os.path.join(folder, name + '.sublime-project')
        if os.path.exists(project_file) and not sublime.ok_cancel_dialog(
                '{} exists. Replace it?'.format(project_file), 'Replace'):
            return
        project = {'folders': [{'name': name, 'path': folder}],
                   'settings': {connections.KEY: settings, 'format_process_on_update': True}}
        with open(project_file, 'w', encoding='utf-8') as f:
            json.dump(project, f, indent=4)
        open_project(project_file)


class UpdateTm1Project(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return bool(self.window.project_file_name())

    def run(self):
        settings = (self.window.project_data() or {}).get('settings', {})
        try:
            current = connections.from_project_settings(settings)
            initial = '{}://{}:{}'.format('https' if current.ssl else 'http', current.address, current.port)
        except connections.NotConfigured:
            initial = ''
        Setup(self.window, self.save, initial).start()

    def save(self, tm1_settings):
        project = self.window.project_data() or {}
        settings = project.setdefault('settings', {})
        settings[connections.KEY] = tm1_settings
        self.window.set_project_data(project)
        self.window.status_message('TM1: connection updated')
        if connections.has_stored_password(settings):
            items = [sublime.QuickPanelItem('Remove it', details='TM1 asks for the password when it connects'),
                     sublime.QuickPanelItem('Keep it', details='Needed while someone uses this project with 0.2.x')]

            def chosen(index):
                if index == 0:
                    project['settings'] = connections.without_stored_passwords(settings)
                    self.window.set_project_data(project)

            self.window.show_quick_panel(items, chosen,
                                         placeholder='This project still holds the password 0.2.x stored. Remove it?')


class Tm1SignOutCommand(sublime_plugin.WindowCommand):
    """TM1: Config - Sign Out: forgets this project's password and passport, and can also forget the
    browser sign-in (its profile), so the next connection starts afresh."""

    def is_enabled(self):
        return bool(self.window.project_file_name())

    def run(self):
        key = self.window.project_file_name()
        credentials.forget(key)
        browser_sign_in.forget(key)
        stale = gateway._gateways.pop(key, None)
        if stale is not None:
            stale.close()
        items = [sublime.QuickPanelItem('Done', details='The next connection asks again'),
                 sublime.QuickPanelItem('Also forget the browser sign-in',
                                        details="The identity provider won't remember you either")]

        def chosen(index):
            if index == 1:
                shutil.rmtree(browser_sign_in.profile_folder(), ignore_errors=True)
            self.window.status_message('TM1: signed out')

        self.window.show_quick_panel(items, chosen, placeholder='Signed out of TM1 for this project')
