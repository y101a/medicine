"""API 延迟分位数与吞吐压测（只打零付费、不调模型的路径）。

用法：python bench_load.py --concurrency 10 --duration 8
"""

import argparse
import asyncio
import json
import math
import time
import uuid
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8010/api/v1"
USERNAME = "bench_load_user"
PASSWORD = "Bench!Load#2026"
OUT = Path(__file__).with_name("bench_result.json")

NORMAL_TEXTS = [
    "最近有点头晕，平时需要注意什么？",
    "孩子发烧到 38 度，家里应该怎么护理？",
    "每天走一万步对膝盖有影响吗？",
]
RED_FLAG_TEXTS = [
    "我胸口疼得厉害",
    "孩子突然抽搐了",
]


def percentiles(values: list[float]) -> dict:
    if not values:
        return {}
    ordered = sorted(values)

    def pick(ratio: float) -> float:
        index = max(0, math.ceil(ratio * len(ordered)) - 1)
        return round(ordered[index], 1)

    return {
        "mean": round(sum(ordered) / len(ordered), 1),
        "p50": pick(0.50),
        "p90": pick(0.90),
        "p99": pick(0.99),
        "max": round(ordered[-1], 1),
    }


async def request_once(client: httpx.AsyncClient, spec: dict) -> tuple[int, float]:
    start = time.perf_counter()
    try:
        response = await client.request(spec["method"], spec["url"], json=spec.get("json"))
        status = response.status_code
    except Exception:  # noqa: BLE001
        status = -1
    return status, (time.perf_counter() - start) * 1000


async def run_scenario(
    name: str, client: httpx.AsyncClient, make_spec, concurrency: int, duration: float
) -> dict:
    for _ in range(20):  # 预热，避免首请求开销污染 p99
        await request_once(client, make_spec())

    latencies: list[float] = []
    statuses: dict[int, int] = {}
    deadline = time.perf_counter() + duration
    lock = asyncio.Lock()

    async def worker() -> None:
        while time.perf_counter() < deadline:
            status, elapsed = await request_once(client, make_spec())
            async with lock:
                latencies.append(elapsed)
                statuses[status] = statuses.get(status, 0) + 1

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    elapsed_total = time.perf_counter() - started

    ok = statuses.get(200, 0) + statuses.get(201, 0)
    result = {
        "scenario": name,
        "concurrency": concurrency,
        "seconds": round(elapsed_total, 2),
        "requests": len(latencies),
        "ok": ok,
        "errors": len(latencies) - ok,
        "rps": round(len(latencies) / elapsed_total, 1),
        "status_codes": {str(k): v for k, v in sorted(statuses.items())},
        **percentiles(latencies),
    }
    return result


def scenarios(client: httpx.AsyncClient, cid: str) -> dict:
    counter = {"n": 0}

    def next_text() -> str:
        counter["n"] += 1
        pool = NORMAL_TEXTS if counter["n"] % 5 else RED_FLAG_TEXTS
        return pool[counter["n"] % len(pool)]

    return {
        "login（Argon2 校验 + 写会话）": lambda: {
            "method": "POST",
            "url": f"{BASE}/auth/login",
            "json": {"username": USERNAME, "password": PASSWORD},
        },
        "list_consultations（分页读）": lambda: {
            "method": "GET",
            "url": f"{BASE}/consultations?offset=0&limit=20",
        },
        "create_consultation（写）": lambda: {
            "method": "POST",
            "url": f"{BASE}/consultations",
            "json": {"clientRequestId": str(uuid.uuid4())},
        },
        "post_message（写 + 红旗预检）": lambda: {
            "method": "POST",
            "url": f"{BASE}/consultations/{cid}/messages",
            "json": {
                "content": next_text(),
                "clientRequestId": str(uuid.uuid4()),
            },
        },
        "get_messages（分页读）": lambda: {
            "method": "GET",
            "url": f"{BASE}/consultations/{cid}/messages?offset=0&limit=20",
        },
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--duration", type=float, default=8.0)
    args = parser.parse_args()

    # trust_env=False：绕过 Windows 系统代理，否则本机请求会被代理拦成 502
    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        login = await client.post(
            f"{BASE}/auth/login", json={"username": USERNAME, "password": PASSWORD}
        )
        print("登录状态码:", login.status_code)
        if login.status_code != 200:
            print("登录失败，响应:", login.text[:300])
            return

        created = await client.post(
            f"{BASE}/consultations",
            json={"clientRequestId": str(uuid.uuid4())},
        )
        print("建会话状态码:", created.status_code)
        if created.status_code != 201:
            print("建会话失败，响应:", created.text[:300])
            return
        cid = created.json()["id"]

        results = []
        for name, make_spec in scenarios(client, cid).items():
            result = await run_scenario(
                name, client, make_spec, args.concurrency, args.duration
            )
            results.append(result)
            print(
                f"{result['scenario']:<34} RPS={result['rps']:>7} "
                f"p50={result['p50']:>7} p90={result['p90']:>7} "
                f"p99={result['p99']:>7} max={result['max']:>8} "
                f"ok={result['ok']} err={result['errors']} codes={result['status_codes']}"
            )

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("结果已写入:", OUT)


if __name__ == "__main__":
    asyncio.run(main())