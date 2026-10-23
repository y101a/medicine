import asyncio
import importlib.util
from pathlib import Path

import httpx

spec = importlib.util.spec_from_file_location(
    "performance_load", Path(__file__).resolve().parents[1] / "scripts/performance_load.py"
)
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)


def test_percentiles_and_failed_requests_are_not_successful_qps():
    samples = [{"ms": x, "ok": True, "status": "200"} for x in range(1, 101)]
    samples.append({"ms": 2000, "ok": False, "status": "ReadTimeout"})
    result = load.summarize(samples, 2)
    assert result["successful_qps"] == 50
    assert result["completed_qps"] == 50.5
    assert result["errors"] == 1
    assert result["success_latency_ms"] == {"p50": 50, "p95": 95, "p99": 99}
    assert result["all_attempt_latency_ms"]["p99"] == 100
    assert load.percentile([], 0.99) is None


def test_success_status_without_business_payload_is_not_success():
    assert not load.valid_response("messages", httpx.Response(200, json={"items": []}))
    assert not load.valid_response("profile", httpx.Response(200, text="not json"))
    assert not load.valid_response("profile", httpx.Response(401, json={"id": "fake"}))
    assert not load.valid_response("triage_write", httpx.Response(201, json={"id": "x"}))
    assert load.valid_response(
        "triage_write", httpx.Response(201, json={"id": "x", "triage": {"level": "emergency"}})
    )


async def test_phase_synchronizes_workers_and_counts_timeouts():
    seen = set()

    async def handler(request):
        seen.add(request.headers["cookie"])
        await asyncio.sleep(0.002)
        if request.headers["cookie"] == "bad":
            raise httpx.ReadTimeout("synthetic timeout")
        return httpx.Response(200, json={"id": "synthetic"})

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1", transport=httpx.MockTransport(handler)
    ) as client:
        samples, elapsed = await load.phase(
            client, [{"cookie": "good"}, {"cookie": "bad"}], "profile", 2, 0.03
        )
    assert seen == {"good", "bad"}
    assert elapsed >= 0.03
    assert any(x["status"] == "ReadTimeout" and not x["ok"] for x in samples)
    assert any(x["ok"] for x in samples)
