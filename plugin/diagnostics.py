"""TM1's compile and rule errors, shown in the file: the line highlighted, the message beside it."""

import html

import sublime
import sublime_plugin

KEY = 'tm1.errors'
# 0.2.x's key, cleared too, so its highlights don't linger after the upgrade
LEGACY_KEY = 'error'


def show(view, errors):
    """Highlights each (0-based line, message) and shows the first."""
    clear(view)
    regions, notes = [], []
    for line, message in errors:
        regions.append(view.line(view.text_point(line, 0)))
        notes.append('<span>{}</span>'.format(html.escape(message)))
    view.add_regions(KEY, regions, scope='invalid', flags=sublime.DRAW_NO_FILL | sublime.DRAW_SQUIGGLY_UNDERLINE
                     | sublime.DRAW_NO_OUTLINE, annotations=notes, annotation_color='#e05252')
    if regions:
        view.show_at_center(regions[0])


def clear(view):
    view.erase_regions(KEY)
    view.erase_regions(LEGACY_KEY)


class Tm1DiagnosticsListener(sublime_plugin.EventListener):
    """Clears the errors when the file is saved again: they describe what was put, not what's there now."""

    def on_pre_save(self, view):
        file_name = view.file_name() or ''
        if file_name.endswith(('.pro', '.rux')):
            clear(view)
