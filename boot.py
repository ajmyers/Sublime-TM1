import sublime_plugin

import sys
import os

base_path = os.path.realpath(__file__)
base_path = os.path.split(base_path)[0]

sys.path.insert(0, os.path.join(base_path))
sys.path.insert(0, os.path.join(base_path, 'include', 'wcwidth'))
sys.path.insert(0, os.path.join(base_path, 'include', 'prettytable', 'src', 'prettytable'))
sys.path.insert(0, os.path.join(base_path, 'include', 'TM1py'))
sys.path.insert(0, os.path.join(base_path, 'include', 'mdxpy'))
sys.path.insert(0, os.path.join(base_path, 'include', 'urllib3', 'src'))
sys.path.insert(0, os.path.join(base_path, 'include', 'requests'))
sys.path.insert(0, os.path.join(base_path, 'include', 'charset_normalizer'))
sys.path.insert(0, os.path.join(base_path, 'include', 'idna'))
sys.path.insert(0, os.path.join(base_path, 'include', 'ijson'))
sys.path.insert(0, os.path.join(base_path, 'include', 'pytz', 'src'))
sys.path.insert(0, os.path.join(base_path, 'include', 'pyyaml', 'lib'))

from .commands.GetObjectsFromServer import GetObjectsFromServer
from .commands.PutObjectToServer import PutObjectToServer
from .commands.RunTurboIntegratorProcess import RunTurboIntegratorProcess
from .commands.UpdateTm1Project import UpdateTm1Project
from .commands.ClearTurboIntegratorLogs import ClearTurboIntegratorLogs
from .commands.DisplayTm1OpsConsoleCommand import DisplayTm1OpsConsole
from .commands.DisplayTm1OpsConsoleCommand import KillTm1ThreadCommand
from .commands.RefreshTm1OpsConsole import RefreshTm1OpsConsoleCommand
from .commands.FormatTurboIntegratorProcess import *
from .commands.ProjectCompletions import ProjectCompletions
from .commands.CreateNewTm1Project import CreateNewTm1Project
# from .commands.Test import RunTest
