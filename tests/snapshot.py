"""Compares text with a file in tests/snapshots/. UPDATE_SNAPSHOTS=1 writes the files instead."""

import os

SNAPSHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'snapshots')


def matches_snapshot(name, text):
    path = os.path.join(SNAPSHOTS, name)
    if os.environ.get('UPDATE_SNAPSHOTS') == '1':
        os.makedirs(SNAPSHOTS, exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
    with open(path, encoding='utf-8', newline='') as f:
        expected = f.read()
    assert text == expected, 'differs from tests/snapshots/{} (UPDATE_SNAPSHOTS=1 rewrites it)'.format(name)


def read_snapshot(name):
    with open(os.path.join(SNAPSHOTS, name), encoding='utf-8', newline='') as f:
        return f.read()
