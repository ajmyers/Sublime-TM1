import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.join(ROOT, 'tests', 'stubs'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))

# The libraries copied into include/, as boot.py puts them on sys.path. They go away with the
# move to skipcheck-tm1 installed through Package Control.
for path in ['wcwidth', 'prettytable/src/prettytable', 'TM1py', 'mdxpy', 'urllib3/src', 'requests',
             'charset_normalizer', 'idna', 'ijson', 'pytz/src', 'pyyaml/lib']:
    sys.path.insert(0, os.path.join(ROOT, 'include', path))

# The repository is a Sublime Text package: its modules import each other relatively, under the
# package's name. Tests import it as `tm1pkg`.
package = types.ModuleType('tm1pkg')
package.__path__ = [ROOT]
sys.modules['tm1pkg'] = package
