"""Concurrent HTTP load generator for the movie API: a mix of point-read
GETs and rating-update POSTs, run for a fixed duration with a thread pool.
"""
import argparse
import csv
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import urllib.request
import urllib.error

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def load_movie_ids():
    ids = []
    with open(os.path.join(DATA_DIR, "movies.csv")) as f:
        for row in csv.DictReader(f):
            ids.append(row["movieId"])
    return ids


def _one_request(base_url, movie_ids, write_ratio, rng, request_timeout):
    movie_id = rng.choice(movie_ids)
    is_write = rng.random() < write_ratio
    start = time.perf_counter()
    try:
        if is_write:
            body = json.dumps({"rating": round(rng.uniform(0.5, 5.0) * 2) / 2}).encode()
            req = urllib.request.Request(
                f"{base_url}/movies/{movie_id}/rate", data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
        else:
            req = urllib.request.Request(f"{base_url}/movies/{movie_id}")
        with urllib.request.urlopen(req, timeout=request_timeout) as resp:
            resp.read()
            ok = 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError, OSError):
        ok = False
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms, ok


def run_load_test(base_url, duration=15, concurrency=20, write_ratio=0.2, seed=42,
                   fault_fn=None, fault_at_s=None, request_timeout=1.5):
    """Runs a concurrent load test. If fault_fn is given, it is invoked once
    from the main thread at fault_at_s seconds into the run (e.g. to `docker
    kill` a backend mid-traffic). request_timeout is kept short so a dead
    backend fails a request quickly instead of parking a worker thread for
    the whole timeout window - which would starve the sample rate exactly
    when fine-grained recovery visibility matters most. Returns per-second
    error-rate buckets plus an explicit recovery_time_s: the gap between the
    fault firing and the first successful request seen after it (None if no
    success was observed again before the test ended).
    """
    movie_ids = load_movie_ids()
    t_start = time.time()
    stop_at = t_start + duration
    records = []  # (timestamp, elapsed_ms, ok)
    lock = threading.Lock()

    def worker(worker_id):
        rng = random.Random(seed + worker_id)
        local = []
        while time.time() < stop_at:
            ts = time.time()
            elapsed_ms, ok = _one_request(base_url, movie_ids, write_ratio, rng, request_timeout)
            local.append((ts, elapsed_ms, ok))
        with lock:
            records.extend(local)

    fault_ts = {"value": None}

    def fault_watcher():
        if fault_fn is None:
            return
        time.sleep(fault_at_s)
        fault_ts["value"] = time.time()
        fault_fn()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    watcher = threading.Thread(target=fault_watcher) if fault_fn else None
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    if watcher:
        watcher.start()
    for t in threads:
        t.join()
    if watcher:
        watcher.join()
    wall_time = time.perf_counter() - t0

    records.sort(key=lambda r: r[0])
    latencies = sorted(r[1] for r in records)
    n = len(latencies)
    errors = sum(1 for r in records if not r[2])

    def pct(p):
        return latencies[min(int(n * p), n - 1)] if n else 0.0

    buckets = {}
    for ts, _, ok in records:
        b = int(ts - t_start)
        d = buckets.setdefault(b, {"total": 0, "errors": 0})
        d["total"] += 1
        if not ok:
            d["errors"] += 1
    per_second = [
        {"second": b, "total": v["total"], "errors": v["errors"],
         "error_rate": v["errors"] / v["total"] if v["total"] else 0.0}
        for b, v in sorted(buckets.items())
    ]

    recovery_time_s = None
    if fault_ts["value"] is not None:
        # A request that started just before the kill can still complete
        # successfully just after fault_ts (it was already in flight against
        # the still-alive process) - that is not "recovery". So: first find
        # the first actual failure after the fault (outage confirmed), then
        # measure the gap to the first success after that failure.
        outage_start = next((ts for ts, _, ok in records if ts > fault_ts["value"] and not ok), None)
        if outage_start is not None:
            recovery_ts = next((ts for ts, _, ok in records if ts > outage_start and ok), None)
            recovery_time_s = (recovery_ts - fault_ts["value"]) if recovery_ts else None
        else:
            recovery_time_s = 0.0  # fault fired but caused no observed failure

    return {
        "requests": n,
        "errors": errors,
        "wall_time_s": wall_time,
        "throughput_rps": n / wall_time if wall_time else 0.0,
        "mean_ms": sum(latencies) / n if n else 0.0,
        "p50_ms": pct(0.50),
        "p95_ms": pct(0.95),
        "p99_ms": pct(0.99),
        "per_second": per_second,
        "recovery_time_s": recovery_time_s,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--duration", type=float, default=15)
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--write-ratio", type=float, default=0.2)
    args = ap.parse_args()
    result = run_load_test(args.url, args.duration, args.concurrency, args.write_ratio)
    print(json.dumps(result, indent=2))
