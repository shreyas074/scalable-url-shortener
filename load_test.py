"""
Quick-and-dirty load test to generate real numbers you can quote on your
resume/in interviews (e.g. "handled X req/sec at p99 of Y ms").

Usage:
    python load_test.py --requests 500 --concurrency 20

Requires the server to already be running (uvicorn app.main:app).
"""
import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

BASE_URL = "http://127.0.0.1:8000"


def create_short_url(client: httpx.Client) -> str:
    resp = client.post(f"{BASE_URL}/api/shorten", json={"url": "https://www.anthropic.com"})
    resp.raise_for_status()
    return resp.json()["short_code"]


def hit_redirect(client: httpx.Client, short_code: str) -> float:
    start = time.perf_counter()
    client.get(f"{BASE_URL}/{short_code}", follow_redirects=False)
    return (time.perf_counter() - start) * 1000  # ms


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()

    with httpx.Client() as setup_client:
        short_code = create_short_url(setup_client)

    print(f"Load testing GET /{short_code} redirect")
    print(f"Total requests: {args.requests}, concurrency: {args.concurrency}\n")

    latencies = []
    start_all = time.perf_counter()

    def worker(_):
        with httpx.Client() as client:
            return hit_redirect(client, short_code)

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for latency in pool.map(worker, range(args.requests)):
            latencies.append(latency)

    total_time = time.perf_counter() - start_all
    latencies.sort()

    def percentile(p):
        idx = int(len(latencies) * p / 100)
        return latencies[min(idx, len(latencies) - 1)]

    print(f"Total time:     {total_time:.2f}s")
    print(f"Throughput:     {args.requests / total_time:.1f} req/sec")
    print(f"Avg latency:    {statistics.mean(latencies):.2f} ms")
    print(f"p50 latency:    {percentile(50):.2f} ms")
    print(f"p95 latency:    {percentile(95):.2f} ms")
    print(f"p99 latency:    {percentile(99):.2f} ms")


if __name__ == "__main__":
    main()
