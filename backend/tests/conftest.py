import pytest
from test_profile import profile_context  # noqa: F401

from app.core.config import get_settings
from app.services import health_records
from app.services.news import auto as news_auto


@pytest.fixture(autouse=True)
def _disable_news_auto_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认关闭资讯的「每日首次访问自动刷新」（N3）。

    它刻意脱离请求事务：开自己的会话、访问外网、写开发库——和上面健康记录抽取同一类问题。
    另外开关来自开发者 `.env` 的 `NEWS_PORTAL_ENABLED`，测试不能跟着本机配置走。
    要覆盖真实触发链路的测试自行打开（见 ``tests/test_news_auto.py`` 的 ``hooks``）。
    """

    monkeypatch.setattr(get_settings(), "news_portal_enabled", False)
    monkeypatch.setattr(news_auto, "AUTO_REFRESH_ENABLED", False)


@pytest.fixture(autouse=True)
def _disable_detached_health_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认关闭「服务端健康记录抽取」的后台派发。

    该派发刻意脱离请求事务：它开自己的会话，并可能使用真实模型凭据。在测试进程里
    那意味着写到开发库、甚至发起真实付费调用，因此默认关闭。要覆盖真实触发链路的
    测试自行打开开关，并把 ``EXTRACTION_SESSION_FACTORY`` 指向事务内测试会话
    （见 ``tests/test_health_record_auto_extraction.py``）。
    """

    monkeypatch.setattr(health_records, "EXTRACTION_SCHEDULING_ENABLED", False)