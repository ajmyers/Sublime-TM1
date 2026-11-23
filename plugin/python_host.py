"""Works around faults of the Python that Sublime Text runs plugins on."""

import sysconfig


def work_around_missing_sysconfigdata():
    """Sublime Text 4213 to 4215's macOS build ships Linux's sysconfig data
    (_sysconfigdata__linux_x86_64-linux-gnu) in its Python 3.14 instead of macOS's, so the plugin
    host's first sysconfig.get_config_vars() raises ModuleNotFoundError. zoneinfo asks sysconfig for
    TZPATH when it's first imported, and pydantic imports zoneinfo, so skipcheck-tm1 fails to load.

    sysconfig keeps the config it had when it failed (none), so later calls return no config instead
    of raising, which is all zoneinfo needs. Making the first call here, before anything imports
    pydantic, is enough. Where sysconfig works, this call is just a lookup."""
    try:
        sysconfig.get_config_vars()
    except ModuleNotFoundError:
        pass
