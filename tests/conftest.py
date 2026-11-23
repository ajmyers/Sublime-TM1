import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.join(ROOT, 'tests', 'stubs'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))


# The repository is a Sublime Text package: its modules import each other relatively, under the
# package's name. Tests import it as `tm1pkg`.
package = types.ModuleType('tm1pkg')
package.__path__ = [ROOT]
sys.modules['tm1pkg'] = package
