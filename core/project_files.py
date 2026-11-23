"""The rule and process files Get keeps in a project, mirroring the server."""

import glob
import os

from .process_file import process_to_text
from .rule_file import rules_to_text

RULES = 'rules'
PROCESSES = 'processes'


def mirror(folder, cubes, processes):
    """Writes each cube's rules to rules/<cube>.rux and each process to processes/<name>.pro, then
    deletes the files there the server no longer has. Only the package's own files: .rux in rules/
    and .pro in processes/, and any .pro/.rux in the root folder, where version 0.1 wrote them.
    ``cubes`` are (name, dimension names, rules) triples; a cube without rules gets no file.
    Returns how many rule and process files it wrote, and how many it deleted."""
    wanted = {}
    for name, dimensions, rules in cubes:
        if rules:
            wanted[os.path.join(folder, RULES, name + '.rux')] = rules_to_text(name, dimensions, rules)
    for process in processes:
        wanted[os.path.join(folder, PROCESSES, process.name + '.pro')] = process_to_text(process)

    existing = (glob.glob(os.path.join(folder, RULES, '*.rux')) + glob.glob(os.path.join(folder, PROCESSES, '*.pro'))
                + glob.glob(os.path.join(folder, '*.rux')) + glob.glob(os.path.join(folder, '*.pro')))
    deleted = 0
    for path in existing:
        if path not in wanted:
            os.remove(path)
            deleted += 1

    for path, text in wanted.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Text mode, as 0.2.x wrote them: the platform's line endings, so a Windows project's
        # files don't all change on the first Get after the upgrade
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)

    rules = sum(1 for path in wanted if path.endswith('.rux'))
    return rules, len(wanted) - rules, deleted
