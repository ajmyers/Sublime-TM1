
rm -rf "/Users/andrewmyers/Library/Application Support/Sublime Text 3/Installed Packages/TM1 Planning Analytics Developer Tools.sublime-package" || true
zip -rv "/Users/andrewmyers/Library/Application Support/Sublime Text 3/Installed Packages/TM1 Planning Analytics Developer Tools.sublime-package" . -x "*.git*" -x "env/*"

rm -rf "/Users/andrewmyers/Library/Application Support/Sublime Text 3/Packages/TM1py" || true
#cp -Rv "/Users/andrewmyers/Documents/Projects/TM1py" "/Users/andrewmyers/Library/Application Support/Sublime Text 3/Packages/TM1py"

killall sublime_text
sleep .5
open -a 'Sublime Text'