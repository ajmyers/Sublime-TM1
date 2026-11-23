"""TM1: Run - Execute Turbo Integrator Process, and TM1: Run - Clear Log Files."""

import os
import tempfile
import time

import sublime
import sublime_plugin

from ..core import run_log
from ..core.table import table
from . import gateway

PANEL = 'TM1 Run'
LOG_FOLDER = 'Turbo Integrator Logs'
DIVIDER = '-' * 51


def execute(name, parameters, async_requests=True):
    """The run on TM1: its status, its message-log entries, and the error files it wrote."""
    def work(client):
        last = client.logs.message_log_entries(orderby='TimeStamp desc', top=1)
        runner = client.with_async(1) if async_requests else client
        result = runner.processes.execute_with_return(name, parameters=parameters or None, expand='ErrorLogFile')
        query = {'orderby': 'TimeStamp asc', 'top': 1000}
        if last:
            query['filter'] = 'TimeStamp ge {}'.format(last[0].time_stamp.isoformat().replace('+00:00', 'Z'))
        # TM1 can answer before the run's last lines are in its log: read again until the run's start
        # and end are both there, for a few seconds
        messages = []
        for attempt in range(7):
            entries = sorted(client.logs.message_log_entries(**query), key=run_log.order)
            messages = run_log.run_messages(entries, name)
            if run_log.complete(messages, name):
                break
            time.sleep(0.5)
        files = run_log.error_files(messages)
        if result.error_log_file and result.error_log_file.filename and result.error_log_file.filename not in files:
            files.insert(0, result.error_log_file.filename)
        contents = {}
        for file_name in files:
            try:
                contents[file_name] = client.logs.error_log_content(file_name)
            except Exception as e:
                contents[file_name] = '(not read: {})'.format(e)
        return result.process_execute_status_code.value, messages, contents
    return work


def log_folder(window):
    """The project's "Turbo Integrator Logs" folder, added to the project as 0.2.x did."""
    project = window.project_data() or {}
    folders = [f for f in project.get('folders', []) if os.path.exists(f.get('path', ''))]
    for folder in folders:
        if folder.get('name') == LOG_FOLDER:
            return folder['path']
    path = tempfile.mkdtemp(prefix='sublime-tm1-ti-logs-')
    folders.append({'name': LOG_FOLDER, 'path': path})
    project['folders'] = folders
    window.set_project_data(project)
    return path


def append(window, text):
    panel = window.find_output_panel(PANEL) or window.create_output_panel(PANEL)
    panel.run_command('append', {'characters': text, 'force': True, 'scroll_to_end': True})


class RunTurboIntegratorProcess(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return bool(self.window.project_file_name())

    def run(self, process=None, confirm=None, **parameters):
        tm1 = gateway.for_window(self.window)
        if tm1 is None:
            return
        if process and confirm == 'Yes':
            # As 0.2.x was called with arguments (a keybinding, say): run it as asked
            self.start(tm1, process, parameters)
        elif not confirm:
            self.window.status_message('TM1: listing processes...')
            tm1.run(self.window, lambda c: [p.name for p in c.processes.list(select='Name')],
                    lambda names: self.choose(tm1, names))

    def choose(self, tm1, names):
        names = run_log.callers_first(names)
        view = self.window.active_view()
        current = os.path.splitext(os.path.basename((view.file_name() or '') if view else ''))[0]
        selected = names.index(current) if current in names else 0

        def chosen(index):
            if index >= 0:
                tm1.run(self.window, lambda c: c.processes.get(names[index], select='Name', expand='Parameters'),
                        lambda process: self.ask(tm1, process, list(process.parameters or []), {}))

        self.window.show_quick_panel(names, chosen, selected_index=selected, placeholder='Process to run')

    def ask(self, tm1, process, remaining, values):
        if not remaining:
            self.confirm(tm1, process.name, values)
            return
        parameter = remaining[0]
        numeric = getattr(parameter.type, 'value', parameter.type) == 'Numeric'

        def done(text):
            values[parameter.name] = _number(text) if numeric else text
            self.ask(tm1, process, remaining[1:], values)

        caption = '{}{}:'.format(parameter.name, ' ({})'.format(parameter.prompt) if parameter.prompt else '')
        self.window.show_input_panel(caption, '' if parameter.value is None else str(parameter.value), done, None, None)

    def confirm(self, tm1, name, values):
        details = ['{} = {}'.format(k, v) for k, v in values.items()] or ['no parameters']
        items = [sublime.QuickPanelItem('Run ' + name, details=details), sublime.QuickPanelItem('Cancel')]

        def chosen(index):
            if index == 0:
                self.start(tm1, name, values)

        self.window.show_quick_panel(items, chosen, placeholder='Run {}?'.format(name))

    def start(self, tm1, name, parameters):
        folder = os.path.join(log_folder(self.window), time.strftime('%y%m%d%H%M%S') + '_' + name)
        os.makedirs(folder, exist_ok=True)
        header = [DIVIDER, 'Process : ' + name, 'Run Time: ' + time.strftime('%a, %d %b %Y %H:%M:%S')]
        if parameters:
            header += ['', 'Run Parameters:'] + ['   {} : {}'.format(k, v) for k, v in parameters.items()]
        header.append(DIVIDER)
        text = '\n'.join(header)
        panel = self.window.find_output_panel(PANEL) or self.window.create_output_panel(PANEL)
        self.window.run_command('show_panel', {'panel': 'output.' + PANEL})
        append(self.window, ('\n\n' if panel.size() else '') + text)
        work = execute(name, parameters, tm1.connection.async_requests)

        def done(result):
            status, messages, contents = result
            report = '\n\nProcess completed with status: ' + status
            log = table(['TimeStamp', 'Level', 'Logger', 'Message'],
                        [[m.time_stamp, getattr(m.level, 'value', m.level), m.logger, m.message] for m in messages],
                        max_width=1000)
            if messages:
                report += '\n\n' + log
            for file_name, content in contents.items():
                report += '\n\n{}:\n{}'.format(file_name, content.strip())
            append(self.window, report + '\n')
            _write(folder, '_run.txt', text + report)
            _write(folder, '_tm1server.log', log)
            for file_name, content in contents.items():
                _write(folder, file_name, content)
            self.window.status_message('TM1: {} {}'.format(name, status))

        tm1.run(self.window, work, done)


class ClearTurboIntegratorLogs(sublime_plugin.WindowCommand):
    def run(self):
        project = self.window.project_data() or {}
        project['folders'] = [f for f in project.get('folders', [])
                              if f.get('name') != LOG_FOLDER and os.path.exists(f.get('path', ''))]
        self.window.set_project_data(project)


def _number(text):
    try:
        value = float(text)
    except ValueError:
        return text
    return int(value) if value.is_integer() else value


def _write(folder, name, text):
    with open(os.path.join(folder, name), 'w', encoding='utf-8') as f:
        f.write(text)
