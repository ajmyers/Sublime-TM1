"""TM1: Get - Pull Objects from Server."""

import os

import sublime
import sublime_plugin

from ..core import completions as generated
from ..core import project_files
from . import completions, gateway


def project_folder(window):
    """The project's first folder, where Get keeps the rules and processes. A relative path in the
    project file is relative to the project file."""
    folders = (window.project_data() or {}).get('folders') or []
    if not folders or not folders[0].get('path'):
        return None
    path = os.path.expanduser(folders[0]['path'])
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(window.project_file_name()), path)
    return os.path.normpath(path)


def fetch(client):
    cubes = [(c.name, [d.name for d in c.dimensions or []], c.rules)
             for c in client.cubes.list(select='Name,Rules', expand='Dimensions($select=Name)')]
    return cubes, client.processes.list()


class GetObjectsFromServer(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return bool(self.window.project_file_name())

    def run(self):
        tm1 = gateway.for_window(self.window)
        if tm1 is None:
            return
        folder = project_folder(self.window)
        if folder is None:
            sublime.error_message('TM1: this project has no folder to keep the rules and processes in. '
                                  'Add one with Project > Add Folder to Project.')
            return
        project_file = self.window.project_file_name()
        self.window.status_message('TM1: getting rules and processes from {}...'.format(tm1.connection.base_url))

        def work(client):
            # Files are written here too, off the UI thread: a model can have thousands
            cubes, processes = fetch(client)
            counts = project_files.mirror(folder, cubes, processes)
            completions.store(project_file, generated.build([(n, d) for n, d, _ in cubes], processes))
            return counts

        tm1.run(self.window, work, self.done)

    def done(self, counts):
        rules, processes, deleted = counts
        cleaned = completions.without_generated(self.window.project_data())
        if cleaned is not None:
            self.window.set_project_data(cleaned)
        message = 'TM1: got {} rules and {} processes'.format(rules, processes)
        if deleted:
            message += ', and deleted {} the server no longer has'.format(deleted)
        self.window.status_message(message)
