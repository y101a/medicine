"""北京卫健委来源：不依赖数据库或网络的解析与出网路径约束。"""

import pytest

from app.services.news import fetcher
from app.services.news.adapters import parse_beijing_wjw_health
from app.services.news.fetcher import FetchError


def test_beijing_list_uses_full_title_display_date_and_filters_administration():
    payload = '''<div class="weinei_left_con">
      <div class="weinei_left_con_line">
        <div class="weinei_left_con_line_text"><a
          href="./202609/t20260928_4883552.html"
          title="中秋国庆假期来啦~健康提示请您查收！">
          <span class="pc-hide">中秋国庆假期来啦~健康提示请您查收！</span>
          <span class="mobile-show">中秋国庆假期来啦~健康提示请...</span>
        </a></div><div class="weinei_left_con_line_date">2026-09-25</div>
      </div>
      <div class="weinei_left_con_line"><a href="./202609/t20260911_4860170.html"
        title="2026年服贸会健康卫生服务专题创新成果发布活动在京举行"></a>
        <div class="weinei_left_con_line_date">2026-09-10</div></div>
      <div class="weinei_left_con_line"><a href="./202609/t20260902_4847952.html">
        <span class="pc-hide">北京初秋花粉高峰来了！过敏人群速看防护要点</span>
        <span class="mobile-show">北京初秋花粉高峰来了！过敏...</span></a>
        <div class="weinei_left_con_line_date">2026-09-02</div></div>
      <div class="weinei_left_con_line"><a href="./202608/t20260820_1234567.html"
        title="老年人合理用药指导项目公开遴选公告"></a>
        <div class="weinei_left_con_line_date">2026-08-20</div></div>
    </div>'''.encode()
    entries = parse_beijing_wjw_health(payload)
    assert [(entry.title, entry.category, entry.published_raw) for entry in entries] == [
        ("中秋国庆假期来啦~健康提示请您查收！", "wellness", "2026-09-25"),
        ("北京初秋花粉高峰来了！过敏人群速看防护要点", "disease", "2026-09-02"),
    ]
    assert entries[0].url.endswith("/202609/t20260928_4883552.html")
    assert all(entry.summary_raw is None for entry in entries)


@pytest.mark.parametrize("url", ["https://evil.example/a", "https://wjw.beijing.gov.cn.evil/a"])
async def test_direct_mode_rejects_non_beijing_host_before_network(url):
    with pytest.raises(FetchError, match="FETCH_DIRECT_NOT_ALLOWED"):
        await fetcher.fetch_document(url, timeout_seconds=3, direct_beijing=True)


@pytest.mark.parametrize("direct,expected", [(False, True), (True, False)])
async def test_only_beijing_direct_mode_skips_system_proxy(monkeypatch, direct, expected):
    options = {}

    class StopBeforeNetwork(RuntimeError):
        pass

    def fake_client(**kwargs):
        options.update(kwargs)
        raise StopBeforeNetwork

    monkeypatch.setattr(fetcher.httpx, "AsyncClient", fake_client)
    with pytest.raises(StopBeforeNetwork):
        await fetcher.fetch_document(
            "https://wjw.beijing.gov.cn/xwzx_20031/xwfb/",
            timeout_seconds=3,
            direct_beijing=direct,
        )
    assert options["trust_env"] is expected


async def test_beijing_direct_mode_rejects_cross_host_redirect(monkeypatch):
    class Redirect:
        status_code = 302
        headers = {"location": "https://other.example/news"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return Redirect()

    async def allow_first_host(_url):
        return None

    monkeypatch.setattr(fetcher.httpx, "AsyncClient", lambda **_kwargs: Client())
    monkeypatch.setattr(fetcher, "assert_public_endpoint", allow_first_host)
    with pytest.raises(FetchError, match="FETCH_REDIRECT_INVALID"):
        await fetcher.fetch_document(
            "https://wjw.beijing.gov.cn/xwzx_20031/xwfb/",
            timeout_seconds=3,
            direct_beijing=True,
        )
