import httpx
import pytest
from mcp import Client

from app.ai.mcp.amap import find_nearby_hospitals, search_medical_pois
from app.ai.mcp.models import PubMedSearchResult
from app.ai.mcp.pubmed import ExternalToolError, search_pubmed
from app.ai.mcp.server import build_medical_mcp_server
from app.ai.mcp.validation import ToolInputError, validate_city, validate_topic
from app.core.config import get_settings


def test_mcp_inputs_reject_patient_text_and_exact_address():
    assert validate_topic("哮喘") == "哮喘"
    assert validate_city("110000") == "110000"
    assert validate_city("北京市") == "北京市"
    with pytest.raises(ToolInputError):
        validate_topic("我咳嗽三天，手机号13800138000")
    with pytest.raises(ToolInputError):
        validate_city("北京市海淀区某路10号")


async def test_pubmed_uses_fixed_english_query_and_parses_xml():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["123"]}})
        return httpx.Response(
            200,
            text="""
            <PubmedArticleSet><PubmedArticle><MedlineCitation>
              <PMID>123</PMID><Article><ArticleTitle>Asthma &amp; care</ArticleTitle>
              <Abstract><AbstractText Label="BACKGROUND">An abstract.</AbstractText></Abstract>
              <Journal><Title>Test Journal</Title><JournalIssue><PubDate>
                <Year>2026</Year></PubDate></JournalIssue></Journal>
              </Article></MedlineCitation><PubmedData><ArticleIdList>
                <ArticleId IdType="doi">10.1/example</ArticleId>
              </ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>
            """,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await search_pubmed("哮喘", max_results=3, client=client)

    assert result.query == "asthma"
    assert result.articles[0].pmid == "123"
    assert result.articles[0].title == "Asthma & care"
    assert result.articles[0].abstract == "BACKGROUND: An abstract."
    assert requests[0].url.params["term"] == "asthma"
    assert requests[0].url.params["retmax"] == "3"


async def test_pubmed_rejects_non_numeric_identifiers():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"esearchresult": {"idlist": ["bad"]}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExternalToolError, match="PUBMED_RESPONSE_INVALID"):
            await search_pubmed("哮喘", client=client)


async def test_amap_sends_no_coordinates_and_omits_provider_location():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "status": "1",
                "pois": [
                    {
                        "id": "poi-1",
                        "name": "测试医院",
                        "address": "测试路",
                        "tel": "010-00000000",
                        "pname": "北京市",
                        "cityname": "北京市",
                        "adname": "东城区",
                        "location": "116.1,39.9",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await search_medical_pois(
            "110000",
            "呼吸科",
            api_key="test-only",
            client=client,
        )

    params = captured[0].url.params
    assert params["city"] == "110000"
    assert "location" not in params
    assert "location" not in result.pois[0].model_dump()
    assert result.pois[0].name == "测试医院"


async def test_amap_requires_key_before_network_call():
    with pytest.raises(ExternalToolError, match="AMAP_NOT_CONFIGURED"):
        await search_medical_pois("北京市", "内科", api_key=None)


async def test_nearby_hospitals_converts_gps_and_sorts_by_route_time():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path.endswith("/coordinate/convert"):
            return httpx.Response(200, json={"status": "1", "locations": "116.400000,39.900000"})
        if request.url.path.endswith("/place/around"):
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "pois": [
                        {
                            "id": "far-fast",
                            "name": "甲医院",
                            "address": "甲路",
                            "location": "116.420000,39.900000",
                            "distance": "2000",
                        },
                        {
                            "id": "near-slow",
                            "name": "乙医院",
                            "address": "乙路",
                            "location": "116.410000,39.900000",
                            "distance": "1000",
                        },
                    ],
                },
            )
        duration = "300" if request.url.params["destination"].startswith("116.420000") else "600"
        return httpx.Response(
            200,
            json={
                "status": "1",
                "route": {"paths": [{"distance": "2500", "duration": duration}]},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await find_nearby_hospitals(
            39.89,
            116.39,
            location_consent=True,
            route_mode="driving",
            max_results=2,
            api_key="test-only",
            client=client,
        )

    assert captured[0].url.params["coordsys"] == "gps"
    assert captured[1].url.params["sortrule"] == "distance"
    assert [item.name for item in result.hospitals] == ["甲医院", "乙医院"]
    assert result.hospitals[0].route_duration_seconds == 300
    assert "39.89" not in str(result.model_dump())


async def test_nearby_hospitals_requires_explicit_location_consent():
    with pytest.raises(ToolInputError, match="明确授权"):
        await find_nearby_hospitals(
            39.9,
            116.4,
            location_consent=False,
            api_key="test-only",
        )


async def test_nearby_hospitals_excludes_health_stations():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/coordinate/convert"):
            return httpx.Response(200, json={"status": "1", "locations": "116.4,39.9"})
        if request.url.path.endswith("/place/around"):
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "pois": [
                        {
                            "id": "station",
                            "name": "社区卫生服务站",
                            "location": "116.41,39.9",
                            "distance": "100",
                        },
                        {
                            "id": "hospital",
                            "name": "测试医院",
                            "location": "116.42,39.9",
                            "distance": "200",
                        },
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "1",
                "route": {"paths": [{"distance": "300", "duration": "120"}]},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await find_nearby_hospitals(
            39.9,
            116.4,
            location_consent=True,
            api_key="test-only",
            client=client,
        )

    assert [item.name for item in result.hospitals] == ["测试医院"]


async def test_nearby_hospitals_keeps_candidate_when_route_times_out():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/coordinate/convert"):
            return httpx.Response(200, json={"status": "1", "locations": "116.4,39.9"})
        if request.url.path.endswith("/place/around"):
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "pois": [{
                        "id": "hospital",
                        "name": "测试医院",
                        "location": "116.42,39.9",
                        "distance": "200",
                    }],
                },
            )
        raise httpx.ConnectTimeout("route timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await find_nearby_hospitals(
            39.9,
            116.4,
            location_consent=True,
            api_key="test-only",
            client=client,
        )

    assert result.count == 1
    assert result.hospitals[0].route_duration_seconds is None
    assert "直线距离" in result.notice


async def test_mcp_server_exposes_two_read_only_tools(monkeypatch):
    from app.ai.mcp import server as server_module

    async def fake_pubmed(*_args, **_kwargs):
        return PubMedSearchResult(topic="哮喘", query="asthma", count=0, articles=[])

    monkeypatch.setattr(server_module, "search_pubmed", fake_pubmed)
    server = build_medical_mcp_server(get_settings())
    async with Client(server) as client:
        tools = await client.list_tools()
        result = await client.call_tool("search_pubmed", {"topic": "哮喘"})

    assert {tool.name for tool in tools.tools} == {
        "search_pubmed",
        "search_medical_pois",
        "find_nearby_hospitals",
        "search_hospitals_by_area",
    }
    assert all(tool.annotations.read_only_hint for tool in tools.tools)
    assert result.is_error is False
    assert result.structured_content["query"] == "asthma"
