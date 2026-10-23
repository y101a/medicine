"""Loopback HTTP load generator; real API/database required, no model calls.

Closed-loop concurrency sweeps are measurements of this workload, not an SLA
or an open-loop maximum arrival rate. Never send fixtures to a remote host.
"""

import argparse
import asyncio
import json
import math
import platform
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx

SCENARIOS = ("profile", "consultations", "messages", "triage_write")


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; no interpolation between unobserved samples."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def summarize(samples: list[dict], elapsed: float) -> dict:
    good = [item["ms"] for item in samples if item["ok"]]
    all_times = [item["ms"] for item in samples]
    return {
        "requests": len(samples),
        "successes": len(good),
        "errors": len(samples) - len(good),
        "error_rate": (len(samples) - len(good)) / len(samples) if samples else None,
        "elapsed_seconds": elapsed,
        "successful_qps": len(good) / elapsed if elapsed > 0 else None,
        "completed_qps": len(samples) / elapsed if elapsed > 0 else None,
        "success_latency_ms": {
            f"p{int(p * 100)}": percentile(good, p) for p in (0.5, 0.95, 0.99)
        },
        "all_attempt_latency_ms": {
            f"p{int(p * 100)}": percentile(all_times, p) for p in (0.5, 0.95, 0.99)
        },
        "status_counts": dict(Counter(item["status"] for item in samples)),
        "p99_sample_count_warning": len(good) < 1000,
    }


def request_spec(scenario: str, user: dict) -> tuple[str, str, dict | None]:
    if scenario == "profile":
        return "GET", "/api/v1/users/me", None
    if scenario == "consultations":
        return "GET", "/api/v1/consultations?limit=20", None
    cid = user["consultation_id"]
    if scenario == "messages":
        return "GET", f"/api/v1/consultations/{cid}/messages?limit=50", None
    if scenario == "triage_write":
        return "POST", f"/api/v1/consultations/{user['write_consultation_id']}/messages", {
            "clientRequestId": str(uuid4()),
            "content": "合成压测：突然胸痛，伴有呼吸困难。",
        }
    raise ValueError("Unsupported scenario")


def valid_response(scenario: str, response: httpx.Response) -> bool:
    expected = 201 if scenario == "triage_write" else 200
    if response.status_code != expected:
        return False
    try:
        value = response.json()
        if scenario == "profile":
            return bool(value.get("id"))
        if scenario == "triage_write":
            return bool(value.get("id")) and value.get("triage", {}).get("level") == "emergency"
        return isinstance(value.get("items"), list) and bool(value["items"])
    except (ValueError, AttributeError, TypeError):
        return False


async def phase(client, users, scenario, concurrency, duration) -> tuple[list[dict], float]:
    samples: list[dict] = []
    gate = asyncio.Event()
    deadline = 0.0

    async def worker(index: int):
        user = users[index % len(users)]
        await gate.wait()
        while time.perf_counter() < deadline:
            method, path, body = request_spec(scenario, user)
            started = time.perf_counter()
            try:
                response = await client.request(
                    method, path, json=body,
                    headers={"Cookie": user["cookie"]},
                )
                ok = valid_response(scenario, response)
                status = str(response.status_code) if ok else f"invalid:{response.status_code}"
            except httpx.HTTPError as exc:
                ok, status = False, type(exc).__name__
            samples.append({
                "ms": (time.perf_counter() - started) * 1000,
                "ok": ok,
                "status": status,
            })

    tasks = [asyncio.create_task(worker(i)) for i in range(concurrency)]
    started = time.perf_counter()
    deadline = started + duration
    gate.set()
    await asyncio.gather(*tasks)
    return samples, time.perf_counter() - started


async def run(args):
    target = urlparse(args.base_url)
    if target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Only loopback HTTP targets are permitted")
    if target.username or target.password or target.path not in {"", "/"}:
        raise ValueError("Supply a plain loopback base URL")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    if fixture.get("database") != "medical_assistant_perf" or not fixture.get("users"):
        raise ValueError("Dedicated performance fixture required")
    if max(args.concurrency) > len(fixture["users"]):
        raise ValueError("Prepare at least one fixture user per concurrent worker")
    # Reserve the output before generating any traffic; never overwrite evidence.
    with args.output.open("x", encoding="utf-8") as output:
        report = {
            "created_at": datetime.now(UTC).isoformat(),
            "target": args.base_url,
            "platform": platform.platform(),
            "workload": "closed_loop_no_think_time",
            "fixture_counts": fixture["counts"],
            "duration_per_phase_seconds": args.duration,
            "warmup_per_phase_seconds": args.warmup,
            "model_calls": "excluded",
            "capacity_claim": "not_established_without_SLO_and_sustained_open_loop_test",
            "runs": [],
        }
        async with httpx.AsyncClient(
            base_url=args.base_url, trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(30),
            limits=httpx.Limits(max_connections=max(args.concurrency),
                               max_keepalive_connections=max(args.concurrency)),
        ) as client:
            for scenario in args.scenarios:
                for concurrency in args.concurrency:
                    for repeat in range(args.repeats):
                        if args.warmup:
                            warm, _ = await phase(
                                client, fixture["users"], scenario, concurrency, args.warmup
                            )
                            if not warm or any(not x["ok"] for x in warm):
                                raise RuntimeError("Warmup failed; refuse to benchmark errors")
                        samples, elapsed = await phase(
                            client, fixture["users"], scenario, concurrency, args.duration
                        )
                        row = {"scenario": scenario, "concurrency": concurrency,
                               "repeat": repeat + 1, **summarize(samples, elapsed),
                               "samples": samples}
                        report["runs"].append(row)
                        output.seek(0)
                        json.dump(report, output, ensure_ascii=False, indent=2)
                        output.truncate()
                        output.flush()
                        print(json.dumps({k: v for k, v in row.items() if k != "samples"}),
                              flush=True)
                        if row["error_rate"] and row["error_rate"] > 0.05:
                            raise RuntimeError("Error rate exceeded 5%; stopping load increase")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:58000")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8, 16, 32, 64])
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS,
                        default=list(SCENARIOS[:3]))
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--warmup", type=float, default=5)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if (args.duration <= 0 or args.warmup < 0 or args.repeats < 1
            or any(x < 1 or x > 128 for x in args.concurrency)):
        parser.error("Invalid duration, repeats or concurrency (allowed 1..128)")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
