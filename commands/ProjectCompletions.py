# Originally from https://github.com/bordaigorl/sublime-project-completions/blob/master/ProjectCompletions.py

import sublime
import sublime_plugin


def all_match(view, locs, selector):
    for loc in locs:
        if not view.score_selector(loc, selector):
            return False
    return True


class ProjectCompletions(sublime_plugin.EventListener):

    def on_query_completions(self, view, prefix, locations):
        if view.window() and view.window().project_data():
            completions = view.window().project_data().get("completions")
            if isinstance(completions, list):
                return completions
            elif isinstance(completions, dict):
                result = []
                for selector in completions:
                    if all_match(view, locations, selector):
                        result += [sublime.CompletionItem(**comp) for comp in completions[selector]]
                return result
        return None
