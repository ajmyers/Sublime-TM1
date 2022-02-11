
import json
import os
import sublime
import sublime_plugin

from .connect import get_tm1_service

from .format_process import process_to_view


class GetObjectsFromServerCommand(sublime_plugin.WindowCommand):

    def run(self):
        active_project = sublime.active_window().project_data()
        project_settings = active_project['settings']
        session_settings = project_settings['TM1ConnectionSettings']

        self._settings = project_settings

        completions = []

        self._session = get_tm1_service(session_settings)

        self._folder = sublime.active_window().extract_variables()['folder']
        processes = self._session.processes.get_all()
        for process in processes:
            try:
                self.output_process(process)
                completions.append(self.create_completion(process))
            except Exception as e:
                print('Error extracting process {}, {}'.format(process.name, e))
                pass

        cubes = self._session.cubes.get_all()
        for cube in [x for x in cubes if x.has_rules]:
            try:
                self.output_rule(cube)
            except Exception as e:
                print('Error extracting rule {}, {}'.format(cube.name, e))
                print(e)
                pass

        active_project['completions'] = completions
        sublime.active_window().set_project_data(active_project)

        return

    def create_completion(self, process):
        clean = [(' ', '_'), ('.', '-'), ('}', '')]
        name_clean = process.name.upper()

        for k, v in clean:
            name_clean = name_clean.replace(k, v)

        if len(process.parameters) == 0:
            comp = 'EXECUTEPROCESS(\'{}\');'.format(process.name)
        else:
            comp = 'EXECUTEPROCESS(\'{}\'\n'.format(process.name)
            for x in range(1, len(process.parameters) + 1):
                parameter = process.parameters[x - 1]
                if isinstance(parameter['Value'], str):
                    comp += '   , \'%s\', ${%s:\'%s\'}\n' % (
                        parameter['Name'], str(x), parameter['Value'])
                else:
                    comp += '   , \'%s\', ${%s:%s}\n' % (
                        parameter['Name'], str(x), parameter['Value'])
            comp += ');'

        return ["_TI-{}".format(name_clean), comp]

    def output_rule(self, cube):
        output_file = os.path.join(self._folder, cube.name + '.rux')

        header = ''
        header += '###############################################################################\n'
        header += '### Cube: {}\n'.format(cube.name)
        header += '### Dimensions:\n'

        for index, dimension in enumerate(dim for dim in cube.dimensions if dim != 'Sandboxes'):
            header += '###     {}: {}\n'.format(index + 1, dimension)

        header += '###############################################################################\n\n'

        with open(output_file, 'w', encoding='utf-8') as file:
            file.write(header)
            file.write(cube.rules.text.replace(header, ''))

    def output_process(self, process):
        output_file = os.path.join(self._folder, process.name + '.pro')

        view = process_to_view(process)

        # write file
        with open(output_file, "w", encoding="utf-8") as file:
            file.write(view)

        return
