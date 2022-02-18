import json
import traceback

import requests
from bs4 import BeautifulSoup

from TM1Function import TM1Function

FUNCS = []

SKIP = [
    'Arithmetic Operators in TM1 Rules',
    'Comparison Operators in TM1 Rules',
    'Logical Operators in TM1 Rules',
    'TM1ProcessError.log file',
    'TURBOINTEGRATOR RESERVED WORDS',
    'TurboIntegrator User Variables',
    'IF',
    'WHILE'
]

SKIP = [s.lower() for s in SKIP]


def parse(prefix, url, suffix, func_type):
    page = requests.get(prefix + url + suffix)
    soup = BeautifulSoup(page.text, 'html.parser')

    table = soup.find('ul', attrs={'class': 'ullinks'})

    if table:
        for link in table.find_all('a'):
            parse(prefix, link.get('href'), suffix, func_type)
    else:
        try:
            main = soup.find('main', attrs={'role': 'main'})
            if main:
                func = main.find('h1', attrs={'class': 'topictitle1'})
                func = func.get_text() if func else None
                if not func:
                    print('Unable to parse func')
                    print(main)
                    return

                if func.lower() in SKIP:
                    print('Skip ' + func)
                    return

                desc = main.find('div', attrs={'class': 'abstract'})
                desc = desc.get_text() if desc else ''

                example = main.find('pre', attrs={'class': 'codeblock'})
                example = example.get_text() if example else ''
                example = example.replace('\n', '')

        except Exception as e:
            print(traceback.print_exc())
            return

        FUNCS.append(TM1Function(func, desc, example, func_type, prefix + url))


def generate_completion(scope):
    funcs = [func for func in FUNCS if func.scope == scope]

    completion = dict()

    completion['scope'] = scope
    completion['completions'] = []

    for func in funcs:
        comp = {
            'trigger': func.func,
            'annotation': func.example.replace(' ', '').replace(',', ', '),
            'contents': func.content,
            'kind': func.type,
            'details': func.desc
        }
        completion['completions'].append(comp)

    with open('../completions/' + scope + '.sublime-completions', 'w') as f:
        f.write(json.dumps(completion, sort_keys=False, indent=4))


def cleanup():
    for func in FUNCS:
        if func.func in ['NumericGlobalVariable(\'VariableName\');', 'StringGlobalVariable(\'VariableName\');']:
            func.func = func.func.split('(')[0].upper()
            func.params = ['\'\'']
            func.type = 'function'
            func.refresh()
        elif func.func in ['NValue', 'SValue', 'Value_Is_String', 'DataMinorErrorCount', 'MetadataMinorErrorCount',
                           'ProcessReturnCode', 'PrologMinorErrorCount']:
            func.type = 'variable2'
            func.example = func.func
            func.params = []
            func.refresh()
        elif func.func in ['FEEDERS', 'FEEDSTRINGS', 'SKIPCHECK', 'STET']:
            func.content = func.example


if __name__ == '__main__':
    prefix = 'https://www.ibm.com/docs/api/v1/content/SSD29G_2.0.0/com.ibm.swg.ba.cognos.tm1_ref.2.0.0.doc/'
    suffix = '?parsebody=false&lang=en'

    url = 'c_rulesfunctions_n80006.html'
    parse(prefix, url, suffix, 'rule')

    url = 'c_tm1turbointegratorfunctions_n70006.html'
    parse(prefix, url, suffix, 'process')

    url = 'c_variables_n8000f.html'
    parse(prefix, url, suffix, 'variable')

    cleanup()

    generate_completion('source.tm1')
    generate_completion('source.tm1.rule')
    generate_completion('source.tm1.ti')

    with open('rule_functions.txt', 'w') as f:
        f.write('\n'.join(
            [func.func.lower() for func in FUNCS if func.type == 'function' and func.scope != 'source.tm1.ti']))

    with open('ti_functions.txt', 'w') as f:
        f.write('\n'.join(
            [func.func.lower() for func in FUNCS if func.type == 'function' and func.scope != 'source.tm1.rule']))

    with open('ti_variables.txt', 'w') as f:
        f.write('\n'.join([func.func for func in FUNCS if func.type.startswith('variable')]))
