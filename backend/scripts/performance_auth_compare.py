"""Controlled before/after login load and simultaneous event-loop health probes."""

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from performance_load import summarize  # noqa: E402


def configure():
    os.environ.update({
        "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "55432",
        "POSTGRES_USER": "graph_eval", "POSTGRES_PASSWORD": "graph-eval-local-only",
        "POSTGRES_DB": "medical_assistant_graph_eval", "MCP_ENABLED": "false",
        "NEWS_PORTAL_ENABLED": "false", "WEB_SEARCH_ENABLED": "false",
        "QWEN_API_KEY": "", "DEEPSEEK_API_KEY": "", "KIMI_API_KEY": "",
        "ZHIPUAI_API_KEY": "", "AI_API_KEY": "",
    })


def serve(args):
    configure()
    if args.baseline_auth:
        from app.services import auth

        spec = importlib.util.spec_from_file_location("original_auth", args.baseline_auth)
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        # Replace only in this temporary process, before route imports bind it.
        auth.login_user = baseline.login_user
    import uvicorn

    from app.main import app
    from app.services import health_records
    from app.services.news import auto

    health_records.EXTRACTION_SCHEDULING_ENABLED = False
    auto.AUTO_REFRESH_ENABLED = False
    uvicorn.run(app, host="127.0.0.1", port=58110, access_log=False, log_level="warning")


async def load(args):
    with args.output.open("x", encoding="utf-8") as output:
        report = {"variant": args.variant, "database": "medical_assistant_graph_eval",
                  "duration": args.duration, "worker_count": 1, "account_count": 1,
                  "health_probe_interval": 0.1, "runs": []}
        async with (
            httpx.AsyncClient(base_url="http://127.0.0.1:58110", trust_env=False,
                              timeout=30, limits=httpx.Limits(max_connections=32)) as client,
            httpx.AsyncClient(base_url="http://127.0.0.1:58110", trust_env=False,
                              timeout=30) as probe_client,
        ):
            async def once(client, login):
                started = time.perf_counter()
                try:
                    if login:
                        response = await client.post("/api/v1/auth/login", json={
                            "username": "bench_load_user", "password": "Bench!Load#2026"})
                        ok = response.status_code == 200 and bool(response.json().get("user"))
                    else:
                        response = await client.get("/api/v1/health")
                        ok = response.status_code == 200 and response.json().get("status") == "ok"
                    status = str(response.status_code)
                except (httpx.HTTPError, ValueError, AttributeError) as exc:
                    ok, status = False, type(exc).__name__
                return {"ms": (time.perf_counter() - started) * 1000,
                        "ok": ok, "status": status}

            for concurrency in args.concurrency:
                for repeat in range(args.repeats):
                    for _ in range(5):
                        if not (await once(client, True))["ok"]:
                            raise RuntimeError("Login warmup failed")
                    samples, probes = [], []
                    gate = asyncio.Event()
                    state = {"stop": False, "deadline": 0.0,
                             "samples": samples, "probes": probes}

                    async def worker(state=state, gate=gate):
                        await gate.wait()
                        while time.perf_counter() < state["deadline"]:
                            state["samples"].append(await once(client, True))

                    async def probe(state=state, gate=gate):
                        await gate.wait()
                        while not state["stop"]:
                            state["probes"].append(await once(probe_client, False))
                            await asyncio.sleep(0.1)

                    tasks = [asyncio.create_task(worker()) for _ in range(concurrency)]
                    probe_task = asyncio.create_task(probe())
                    started = time.perf_counter()
                    state["deadline"] = started + args.duration
                    gate.set()
                    await asyncio.gather(*tasks)
                    elapsed = time.perf_counter() - started
                    state["stop"] = True
                    await probe_task
                    row = {"concurrency": concurrency, "repeat": repeat + 1,
                           "login": summarize(samples, elapsed),
                           "health_probe": summarize(probes, elapsed),
                           "login_samples": samples, "probe_samples": probes}
                    report["runs"].append(row)
                    output.seek(0)
                    json.dump(report, output, ensure_ascii=False, indent=2)
                    output.truncate()
                    output.flush()
                    print(json.dumps({k: v for k, v in row.items()
                                      if k not in {"login_samples", "probe_samples"}}), flush=True)
                    if row["login"]["errors"]:
                        raise RuntimeError("Unexpected login failures; stop benchmark")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["serve", "load"])
    parser.add_argument("--baseline-auth", type=Path)
    parser.add_argument("--variant", choices=["before", "after"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 10, 30])
    parser.add_argument("--duration", type=float, default=15)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if args.mode == "serve":
        serve(args)
    else:
        if (not args.variant or not args.output or args.duration <= 0 or args.repeats < 1
                or any(c < 1 or c > 30 for c in args.concurrency)):
            parser.error("Require variant, new output path, positive duration/repeats and c=1..30")
        asyncio.run(load(args))


if __name__ == "__main__":
    main()
