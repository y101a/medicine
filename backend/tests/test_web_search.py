from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.ai.graph.workflow import build_consultation_generation_graph
from app.rag.retrieval import RetrievalCitation, RetrievalResult
from app.rag.web_search import (
    SearchHit,
    WebSearchError,
    generic_topic,
    search_generic_topic,
    trusted_organization,
)


def test_only_fixed_generic_topics_are_extracted():
    assert generic_topic("我叫张三，手机号13812345678，检查说甲状腺结节") == "甲状腺结节"
    assert generic_topic("我头疼三天，住北京市某地") is None
    assert generic_topic("你好") is None
    assert generic_topic("甲状腺相关疾病有哪些") == "甲状腺疾病"
    assert generic_topic("甲状腺疾病") == "甲状腺疾病"
    assert generic_topic("甲状腺有哪些病") == "甲状腺疾病"
    assert generic_topic("甲状腺结节和甲状腺疾病的区别") == "甲状腺结节"
    assert generic_topic("职业性放射性甲状腺疾病怎么治") is None
    assert generic_topic("我甲状腺有点不舒服") is None


def test_only_official_https_domains_are_eligible():
    assert trusted_organization("https://www.nhc.gov.cn/example") == "国家卫生健康委员会"
    assert trusted_organization("https://nhc.gov.cn.evil.test/example") is None
    assert trusted_organization("http://nhc.gov.cn/example") is None
    assert trusted_organization("https://nhc.gov.cn:444/example") is None


async def test_tavily_only_receives_fixed_topic_and_ignores_untrusted_results(monkeypatch):
    from app.rag import web_search

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, url, *, headers, json):
            assert url == "https://api.tavily.com/search"
            assert json["query"] == "甲状腺结节 健康科普 就医"
            assert json["include_answer"] is False
            assert json["include_raw_content"] is False
            assert headers["Authorization"] == "Bearer test-only"
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "results": [
                        {
                            "title": "甲状腺结节科普",
                            "url": "https://www.nhc.gov.cn/test",
                            "content": (
                                "甲状腺结节是常见的体检发现，"
                                "需要结合医生检查报告和实际情况决定是否复诊。"
                            ),
                        },
                        {
                            "title": "甲状腺结节假页面",
                            "url": "https://www.nhc.gov.cn.evil.test/",
                            "content": (
                                "甲状腺结节是常见的体检发现，"
                                "需要结合医生检查报告和实际情况决定是否复诊。"
                            ),
                        },
                        {
                            "title": "健康知识",
                            "url": "https://www.chinacdc.cn/health",
                            "content": (
                                "一般健康知识。" * 80
                                + "甲状腺结节需要结合检查结果由医生判断。"
                            ),
                        },
                    ]
                },
            )

    monkeypatch.setattr(
        web_search,
        "get_settings",
        lambda: SimpleNamespace(
            app_environment="development",
            tavily_api_key=SimpleNamespace(get_secret_value=lambda: "test-only"),
            tavily_base_url="https://api.tavily.com",
        ),
    )
    monkeypatch.setattr(web_search.httpx, "AsyncClient", FakeClient)
    hits = await search_generic_topic(generic_topic("我叫李四 甲状腺结节 身份证110101199001011234"))
    assert len(hits) == 2
    assert hits[0].organization == "国家卫生健康委员会"
    assert "甲状腺结节" in hits[1].excerpt
    assert "李四" not in repr(hits)


async def test_broad_topic_sends_only_fixed_query_and_accepts_disease_specific_pages(monkeypatch):
    from app.rag import web_search

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, url, *, headers, json):
            assert json["query"] == "甲状腺 甲亢 甲减 结节"
            assert "张三" not in json["query"]
            assert "13812345678" not in json["query"]
            assert json["include_raw_content"] is False
            assert headers["Authorization"] == "Bearer test-only"
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"results": [
                    {
                        "title": "甲亢科普",
                        "url": "https://www.nhc.gov.cn/thyroid-a",
                        "content": "甲状腺功能亢进相关的官方科普摘要示例。" * 3,
                    },
                    {
                        "title": "甲减科普",
                        "url": "https://www.chinacdc.cn/thyroid-b",
                        "content": "甲状腺功能减退相关的官方科普摘要示例。" * 3,
                    },
                    {
                        "title": "甲状腺结节假页面",
                        "url": "https://nhc.gov.cn.attacker.invalid/thyroid",
                        "content": "甲状腺结节相关的非官方摘要示例。" * 3,
                    },
                    {
                        "title": "新闻发布会",
                        "url": "https://www.nhc.gov.cn/general-news",
                        "content": "甲亢与甲减在这份较长的会议材料中被顺带提及。" * 3,
                    },
                ]},
            )

    monkeypatch.setattr(
        web_search,
        "get_settings",
        lambda: SimpleNamespace(
            app_environment="development",
            tavily_api_key=SimpleNamespace(get_secret_value=lambda: "test-only"),
            tavily_base_url="https://api.tavily.com",
        ),
    )
    monkeypatch.setattr(web_search.httpx, "AsyncClient", FakeClient)
    topic = generic_topic("张三 13812345678 想知道甲状腺相关疾病有哪些")
    hits = await search_generic_topic(topic)
    assert topic == "甲状腺疾病"
    assert len(hits) == 2
    assert all(hit.url.startswith("https://www.") for hit in hits)
    assert "张三" not in repr(hits)


def thyroid_citation(title: str, content: str) -> RetrievalCitation:
    return RetrievalCitation(
        chunk_id=uuid4(),
        document_id=uuid4(),
        source_key="developer_prototype_knowledge",
        organization="项目开发者",
        title=title,
        canonical_url=f"https://prototype.invalid/{uuid4()}",
        section_title="科普摘要",
        version_label="prototype-test",
        published_at=datetime.now(UTC),
        content=content,
        similarity=0.85,
        trust_level="prototype",
    )


async def test_broad_topic_searches_when_local_covers_only_one_type_and_keeps_both_sources():
    local = thyroid_citation("甲状腺结节科普", "甲状腺结节资料，仅覆盖一种情况。")
    calls = []

    async def fake_retriever(_db, _query, *, top_k):
        return RetrievalResult(False, "test", "v1", [local])

    async def fake_search(topic):
        calls.append(topic)
        return [SearchHit(
            "甲减科普", "https://www.nhc.gov.cn/thyroid-hypo",
            "甲状腺功能减退相关的官方科普摘要示例。" * 3,
            "国家卫生健康委员会",
        )]

    graph = build_consultation_generation_graph(fake_retriever, fake_search)
    result = await graph.ainvoke({"user_text": "甲状腺相关疾病有哪些", "db": object()})
    assert calls == ["甲状腺疾病"]
    assert result["web_search_status"] == "completed"
    assert result["retrieval_status"] == "completed"
    assert {item["source_key"] for item in result["retrieval_items"]} == {
        "developer_prototype_knowledge", "web_search_prototype",
    }


async def test_broad_topic_skips_web_when_local_covers_multiple_types():
    nodule = thyroid_citation("甲状腺结节科普", "甲状腺结节相关资料。")
    hypo = replace(
        nodule, chunk_id=uuid4(), document_id=uuid4(),
        canonical_url="https://prototype.invalid/hypothyroidism",
        title="甲减科普", content="甲状腺功能减退相关资料。",
    )

    async def fake_retriever(_db, _query, *, top_k):
        return RetrievalResult(False, "test", "v1", [nodule, hypo])

    async def unexpected_search(_topic):
        raise AssertionError("本地资料覆盖两个类别时不应联网")

    graph = build_consultation_generation_graph(fake_retriever, unexpected_search)
    result = await graph.ainvoke({"user_text": "甲状腺疾病有哪些", "db": object()})
    assert result["retrieval_status"] == "completed"
    assert result["web_search_status"] == "skipped"
    assert len(result["retrieval_items"]) == 2


async def test_graph_falls_back_when_local_evidence_does_not_cover_topic():
    calls = []

    async def fake_retriever(_db, _query, *, top_k):
        assert top_k == 4
        return RetrievalResult(False, "test", "v1", [])

    async def fake_search(topic):
        calls.append(topic)
        return [
            SearchHit(
                "甲状腺结节科普",
                "https://www.nhc.gov.cn/example",
                "甲状腺结节可以在体检中发现，是否需要就诊要结合医生检查判断。",
                "国家卫生健康委员会",
            )
        ]

    graph = build_consultation_generation_graph(fake_retriever, fake_search)
    result = await graph.ainvoke({"user_text": "我叫李四，甲状腺结节怎么办", "db": object()})
    assert calls == ["甲状腺结节"]
    assert result["web_search_status"] == "completed"
    assert result["retrieval_status"] == "completed"
    assert result["retrieval_items"][0]["trust_level"] == "prototype"
    assert "李四" not in str(result)
    assert "user_text" not in result


async def test_graph_never_searches_for_symptom_without_fixed_topic():
    calls = []

    async def fake_retriever(_db, _query, *, top_k):
        return RetrievalResult(False, "test", "v1", [])

    async def fake_search(topic):
        calls.append(topic)
        return []

    graph = build_consultation_generation_graph(fake_retriever, fake_search)
    result = await graph.ainvoke({"user_text": "头痛了两天，怎么回事", "db": object()})
    assert calls == []
    assert result["web_search_status"] == "skipped"


async def test_graph_rejects_non_official_citation_even_if_searcher_returns_it():
    async def fake_retriever(_db, _query, *, top_k):
        return RetrievalResult(False, "test", "v1", [])

    async def fake_search(topic):
        return [SearchHit(
            "甲状腺结节假资料", "https://nhc.gov.cn.attacker.invalid/claim",
            "甲状腺结节" * 20, "国家卫生健康委员会",
        )]

    graph = build_consultation_generation_graph(fake_retriever, fake_search)
    result = await graph.ainvoke({"user_text": "甲状腺结节是什么意思", "db": object()})
    assert result["retrieval_items"] == []
    assert result["web_search_status"] == "empty"


async def test_search_timeout_is_distinct_from_no_matching_documents():
    async def empty_retriever(_db, _text, *, top_k):
        return RetrievalResult(False, "test", "v1", [])

    async def timeout(_topic):
        raise WebSearchError("WEB_SEARCH_TIMEOUT")

    async def no_matching_documents(_topic):
        return []

    for searcher, status, code in (
        (timeout, "failed", "WEB_SEARCH_TIMEOUT"),
        (no_matching_documents, "empty", None),
    ):
        graph = build_consultation_generation_graph(empty_retriever, searcher)
        result = await graph.ainvoke({"user_text": "甲状腺结节科普", "db": object()})
        assert result["retrieval_status"] == "empty"
        assert result["retrieval_items"] == []
        assert result["web_search_status"] == status
        assert result["web_search_error_code"] == code


async def test_search_client_classifies_timeout_without_exposing_the_key(monkeypatch):
    from app.rag import web_search

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, *_args, **_kwargs):
            raise httpx.ReadTimeout("simulation")

    monkeypatch.setattr(
        web_search, "get_settings",
        lambda: SimpleNamespace(
            app_environment="development",
            tavily_api_key=SimpleNamespace(get_secret_value=lambda: "test-only"),
            tavily_base_url="https://api.tavily.com",
        ),
    )
    monkeypatch.setattr(web_search.httpx, "AsyncClient", FakeClient)
    with pytest.raises(WebSearchError) as error:
        await search_generic_topic("甲状腺结节")
    assert error.value.code == "WEB_SEARCH_TIMEOUT"
    assert "test-only" not in str(error.value)


@pytest.mark.parametrize("question", ("甲状腺结节是什么", "甲状腺相关疾病有哪些"))
async def test_production_never_runs_online_search(monkeypatch, question):
    from app.ai.graph import workflow

    monkeypatch.setattr(
        workflow, "get_settings", lambda: SimpleNamespace(app_environment="production"),
    )

    async def no_local_evidence(_db, _text, *, top_k):
        return RetrievalResult(False, "test", "v1", [])

    async def unexpected_search(_topic):
        raise AssertionError("生产环境不能搜索外网")

    graph = build_consultation_generation_graph(no_local_evidence, unexpected_search)
    result = await graph.ainvoke({"user_text": question, "db": object()})
    assert result["retrieval_status"] == "empty"
    assert result["web_search_status"] == "skipped"
    assert result["web_search_error_code"] is None


async def test_invalid_provider_response_is_not_mislabeled_as_no_results(monkeypatch):
    from app.rag import web_search

    class InvalidClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, url, **_kwargs):
            return httpx.Response(200, request=httpx.Request("POST", url), json={})

    monkeypatch.setattr(
        web_search, "get_settings",
        lambda: SimpleNamespace(
            app_environment="development",
            tavily_api_key=SimpleNamespace(get_secret_value=lambda: "test-only"),
            tavily_base_url="https://api.tavily.com",
        ),
    )
    monkeypatch.setattr(web_search.httpx, "AsyncClient", InvalidClient)
    with pytest.raises(WebSearchError) as error:
        await search_generic_topic("甲状腺结节")
    assert error.value.code == "WEB_SEARCH_INVALID_RESPONSE"
