from TM1py.Services import *
from TM1py.Utils import Utils


class TM1Service:
    """ All features of TM1py are exposed through this service
    
    """

    def __init__(self, **kwargs):
        self._tm1_rest = RESTService(**kwargs)

        # instantiate all Services
        self.chores = ChoreService(self._tm1_rest)
        self.cubes = CubeService(self._tm1_rest)
        self.dimensions = DimensionService(self._tm1_rest)
        self.monitoring = MonitoringService(self._tm1_rest)
        self.processes = ProcessService(self._tm1_rest)
        self.security = SecurityService(self._tm1_rest)
        self.server = ServerService(self._tm1_rest)

        # Deprecated, use cubes.cells instead!
        self.data = CellService(self._tm1_rest)

    def logout(self):
        self._tm1_rest.logout()

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.logout()

    @property
    def version(self):
        return self._tm1_rest._version
