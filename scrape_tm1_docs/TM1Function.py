import csv
import re

with open('./parameter_mapping.csv', newline='\n') as csvfile:
    reader = csv.reader(csvfile, delimiter=',', quotechar='"')
    PARAM_MAPPING = {r[0]: r[1] for r in reader}

DESC_REPLACE = [
    ('TM1Â®', 'TM1'),
    ('This function is valid in both TM1 rules and\n', 'This function is valid in both TM1 rules and '),
    ('This function is valid in TM1 rules and\n', 'This function is valid in TM1 rules and ')
]


class TM1Function:
    def __init__(self, func, desc, example, func_type, url):
        self.func = func.strip()
        self.desc = desc.strip()
        self.example = example.strip()
        self._func_type = func_type
        self.url = url

        if func_type == 'variable':
            self.type = func_type
        else:
            self.type = 'function'
            self.func = self.func.upper()

        self.refresh()

    def refresh(self):
        self._set_desc()
        self._set_scope()
        self._set_params()
        self._set_content()
        self._set_xml_output()

    def _set_content(self):
        if self.type == 'function':
            lst = enumerate(self.params, 1)
            param_content = ['${%s:%s}' % (i, param) for i, param in lst]
            self.content = self.func + '(' + ', '.join(param_content) + ')'
            if self.example.endswith(';'):
                self.content = self.content + ';'
        elif self.type == 'variable':
            self.content = self.func + ' = ' + '${1:}'
        else:
            self.content = self.func

    def _set_xml_output(self):
        out = [
            '<snippet>',
            f'   <content><![CDATA[{self.content}]]></content>',
            f'   <tabTrigger>{self.func}</tabTrigger>',
            f'   <scope>{self.scope}</scope>',
            f'   <description><![CDATA[{self.example}\n\n{self.desc}]]></description>',
            f'</snippet>'
        ]

        self.xml_output = '\n'.join(out)

    def _set_scope(self):
        is_rule = True if self._func_type == 'rule' else False
        is_process = True if self._func_type == 'process' else False

        if self._func_type.startswith('variable'):
            self.scope = 'source.tm1.ti'
            return

        valid_both = [
            'both TM1 rules and TurboIntegrator',
            'valid in TM1 rules and TurboIntegrator'
        ]

        for check in valid_both:
            if check in self.desc:
                is_rule = True
                is_process = True

        if all([is_rule, is_process]):
            self.scope = 'source.tm1'
        elif is_rule:
            self.scope = 'source.tm1.rule'
        else:
            self.scope = 'source.tm1.ti'

    def _set_params(self):
        try:
            matches = re.match(r'(.*?)(\()(.*)(\))', self.example)
            params = matches.group(3)
            params = params.replace('[', '').replace(']', '')
            params = params.split(',')

            self.params_original = params

            params = [p.strip() for p in params]
            params = [PARAM_MAPPING.get(p, p) for p in params]

            self.params = params
        except Exception:
            self.params = []

    def _set_desc(self):
        for rep in DESC_REPLACE:
            self.desc = self.desc.replace(rep[0], rep[1])

        self.desc = '<a href="{}">Documentation</a> '.format(self.url) + self.desc.strip('\n')

    def __repr__(self):
        return f'<TM1: {self.func} ({self.scope})>'
