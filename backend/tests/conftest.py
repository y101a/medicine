import pytest
from test_profile import profile_context  # noqa: F401

from app.services import health_records


@pytest.fixture(autouse=True)
def _disable_detached_health_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认关闭「服务端健康记录抽取」的后台派发。

    该派发刻意脱离请求事务：它开自己的会话，并可能使用真实模型凭据。在测试进程里
    那意味着写到开发库、甚至发起真实付费调用，因此默认关闭。要覆盖真实触发链路的
    测试自行打开开关，并把 ``EXTRACTION_SESSION_FACTORY`` 指向事务内测试会话
    （见 ``tests/test_health_record_auto_extraction.py``）。
    """

    monkeypatch.setattr(health_records, "EXTRACTION_SCHEDULING_ENABLED", False)