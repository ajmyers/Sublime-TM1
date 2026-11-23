"""Builds a Package Control channel holding the library the default channel doesn't have yet,
skipcheck-tm1, for developing the package in Sublime Text before it's published.

    python3 tools/local_channel.py ~/tm1-local-channel

Then add the repository it prints to "repositories" in Packages/User/Package Control.sublime-settings
and run "Package Control: Satisfy Libraries". It builds skipcheck-tm1 from its repository, at the
commit tests/requirements.txt pins; everything it needs is in the default channel. Remove the
entry once skipcheck-tm1 has a final release there.
"""

import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Other libraries the default channel lacks, from PyPI: (name, version, description, issues)
LIBRARIES = []


def skipcheck_requirement():
    with open(os.path.join(HERE, 'tests', 'requirements.txt'), encoding='utf-8') as f:
        for line in f:
            if line.startswith('skipcheck-tm1 @ '):
                return line.split(' @ ', 1)[1].strip()
    raise SystemExit('tests/requirements.txt pins no skipcheck-tm1')


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def release(wheels, wheel, version):
    return {'version': version, 'url': './wheels/' + wheel, 'sha256': sha256(os.path.join(wheels, wheel)),
            'python_versions': ['3.14'], 'platforms': ['*'], 'sublime_text': '>=4213'}


def main(out):
    wheels = os.path.join(out, 'wheels')
    os.makedirs(wheels, exist_ok=True)
    pip = [sys.executable, '-m', 'pip']
    subprocess.run(pip + ['wheel', '--quiet', '--no-deps', '-w', wheels, skipcheck_requirement()], check=True)
    if LIBRARIES:
        subprocess.run(pip + ['download', '--quiet', '--no-deps', '--only-binary=:all:', '-d', wheels]
                       + ['{}=={}'.format(name, version) for name, version, _, _ in LIBRARIES], check=True)

    libraries = []
    for name, version, description, issues in LIBRARIES:
        wheel = next(w for w in os.listdir(wheels) if w.startswith(name + '-' + version + '-'))
        libraries.append({'name': name, 'description': description, 'author': 'encode', 'issues': issues,
                          'releases': [release(wheels, wheel, version)]})
    wheel = next(w for w in os.listdir(wheels) if w.startswith('skipcheck_tm1-'))
    # Package Control wants a semantic version: a development build's ".devN" is dropped
    version = re.match(r'skipcheck_tm1-(\d+\.\d+\.\d+)', wheel).group(1)
    libraries.append({'name': 'skipcheck-tm1', 'author': 'ajmyers',
                      'description': 'Python client for the IBM Planning Analytics (TM1) REST API.',
                      'issues': 'https://github.com/ajmyers/skipcheck-tm1/issues',
                      'releases': [release(wheels, wheel, version)]})

    repository = os.path.join(out, 'repository.json')
    with open(repository, 'w', encoding='utf-8') as f:
        json.dump({'$schema': 'sublime://packagecontrol.io/schemas/repository', 'schema_version': '4.0.0',
                   'packages': [], 'libraries': libraries}, f, indent='\t')
    print('file://' + os.path.abspath(repository))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
