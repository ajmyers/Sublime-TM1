#!/bin/sh
# Builds the package as Package Control would install it, from the committed files
# (git archive leaves out what .gitattributes marks export-ignore), into dist/.
#
# For development, symlink the repository into Sublime's Packages folder instead, so edits
# reload as you save:
#   macOS: ln -s "$PWD" ~/"Library/Application Support/Sublime Text/Packages/TM1 Planning Analytics Developer Tools"
set -eu
cd "$(dirname "$0")"
mkdir -p dist
git archive --format=zip -o "dist/TM1 Planning Analytics Developer Tools.sublime-package" HEAD
echo "dist/TM1 Planning Analytics Developer Tools.sublime-package"
