"""The completions Get generates, and the listener that offers them.

0.2.x wrote them into the project file: thousands of entries for a big model, in a file that's often
shared or committed, and rebuilt every item on each keystroke. Now Get writes them to Sublime's cache
folder, one file per project, and the listener turns them into CompletionItems once.

The listener still offers what the project file's "completions" holds: completions a user wrote
there, and the ones 0.2.x generated, so a project shared with someone on 0.2.x keeps working. After
a Get, the 0.2.x-generated ones are removed from the project (they're recognisable by their
"Auto-generated" details), so they aren't offered twice; a user's own stay.
"""

import hashlib
import json
import os

import sublime
import sublime_plugin

from ..core import completions as generated

PACKAGE = 'TM1 Planning Analytics Developer Tools'

_items = {}


def cache_file(project_file):
    digest = hashlib.sha1(project_file.encode('utf-8')).hexdigest()
    return os.path.join(sublime.cache_path(), PACKAGE, 'completions', digest + '.json')


def store(project_file, by_selector):
    """Saves a project's generated completions (from a worker thread is fine), and drops the items
    built from the earlier ones."""
    path = cache_file(project_file)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'project': project_file, 'completions': by_selector}, f)
    _items.pop(project_file, None)


def _item(completion):
    if isinstance(completion, str):
        return sublime.CompletionItem(completion)
    fields = dict(completion)
    if fields.get('completion_format') == 'snippet':
        fields['completion_format'] = sublime.COMPLETION_FORMAT_SNIPPET
    if fields.get('kind') == 'snippet':
        fields['kind'] = sublime.KIND_SNIPPET
    elif isinstance(fields.get('kind'), list):
        fields['kind'] = tuple(fields['kind'])
    return sublime.CompletionItem(**fields)


def _by_selector(completions):
    if isinstance(completions, list):
        return {'': completions}
    if isinstance(completions, dict):
        return completions
    return {}


def _generated_items(project_file):
    if project_file not in _items:
        try:
            with open(cache_file(project_file), encoding='utf-8') as f:
                data = json.load(f)['completions']
        except (OSError, ValueError, KeyError):
            data = {}
        _items[project_file] = {selector: [_item(c) for c in items] for selector, items in data.items()}
    return _items[project_file]


def without_generated(project_data):
    """The project data without the completions 0.2.x's Get wrote into it; None if it had none."""
    project_completions = (project_data or {}).get('completions')
    if not isinstance(project_completions, dict):
        return None
    kept, removed = {}, False
    for selector, items in project_completions.items():
        mine = [c for c in items if not generated.is_generated(c)] if isinstance(items, list) else items
        removed = removed or mine != items
        if mine:
            kept[selector] = mine
    if not removed:
        return None
    result = dict(project_data)
    if kept:
        result['completions'] = kept
    else:
        result.pop('completions')
    return result


def _matches(view, locations, selector):
    return not selector or all(view.match_selector(location, selector) for location in locations)


class ProjectCompletions(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, locations):
        window = view.window()
        project_file = window.project_file_name() if window else None
        if not project_file:
            return None
        items = []
        for selector, selector_items in _generated_items(project_file).items():
            if _matches(view, locations, selector):
                items += selector_items
        for selector, own in _by_selector((window.project_data() or {}).get('completions')).items():
            if isinstance(own, list) and _matches(view, locations, selector):
                items += [_item(c) for c in own]
        return items or None
