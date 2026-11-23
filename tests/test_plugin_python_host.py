"""plugin.python_host: the sysconfig fault of Sublime Text's macOS Python."""

import sysconfig

from tm1pkg.plugin.python_host import work_around_missing_sysconfigdata


def test_a_failing_first_call_is_swallowed(monkeypatch):
    calls = []

    def missing():
        calls.append(1)
        raise ModuleNotFoundError("No module named '_sysconfigdata__darwin_darwin'")

    monkeypatch.setattr(sysconfig, 'get_config_vars', missing)
    work_around_missing_sysconfigdata()
    assert calls == [1]


def test_where_sysconfig_works_it_is_only_a_lookup():
    work_around_missing_sysconfigdata()
    assert isinstance(sysconfig.get_config_vars(), dict)
