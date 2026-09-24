"""Drives every experiment: build+run each configuration, measure startup
time / resource usage / throughput+latency / fault-recovery, and save raw
JSON results. Requires a working Docker daemon (with Swarm mode available).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from docker_utils import sh, wait_health, docker_stats, image_size_mb, compose_container_ids
from load_test import run_load_test

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results", "raw")
BASE_URL = "http://localhost:8000"


def save_result(name, payload):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"saved {path}")


def compose_up(compose_file, build=True):
    args = ["docker", "compose", "-f", compose_file, "up", "-d"]
    if build:
        args.append("--build")
    sh(args, cwd=PROJECT_ROOT)


def compose_down(compose_file):
    sh(["docker", "compose", "-f", compose_file, "down", "-v"], cwd=PROJECT_ROOT, check=False)


# ---------------------------------------------------------------- Experiment 1: architecture

def run_architecture_experiment():
    print("\n=== Experiment 1: single-container monolith vs multi-container ===")

    # Monolith
    cf = "compose/docker-compose.monolith.yml"
    compose_up(cf)
    try:
        startup = wait_health(f"{BASE_URL}/health")
        time.sleep(2)
        stats = docker_stats(["movie-app-monolith"])
        size = image_size_mb("movie-app:monolith")
        load = run_load_test(BASE_URL, duration=15, concurrency=20)
        save_result("architecture_monolith", {
            "config": "monolith", "startup_time_s": startup, "image_size_mb": size,
            "resources": stats, "load_test": load,
        })
    finally:
        compose_down(cf)

    # Multi-container, 1 app replica
    cf = "compose/docker-compose.multi.yml"
    compose_up(cf)
    try:
        startup = wait_health(f"{BASE_URL}/health")
        time.sleep(2)
        stats = docker_stats(["movie-app-multi", "movie-redis"])
        size = image_size_mb("movie-app:multi")
        load = run_load_test(BASE_URL, duration=15, concurrency=20)
        save_result("architecture_multi", {
            "config": "multi", "startup_time_s": startup, "image_size_mb": size,
            "resources": stats, "load_test": load,
        })

        # Fault test: kill the only app container (no redundancy) - full outage window
        fault = run_load_test(BASE_URL, duration=20, concurrency=15,
                               fault_fn=lambda: sh(["docker", "kill", "movie-app-multi"], check=False),
                               fault_at_s=5)
        save_result("fault_compose_1x", fault)
    finally:
        compose_down(cf)

    # Monolith fault test (separately, since it needs a fresh reseed on restart)
    cf = "compose/docker-compose.monolith.yml"
    compose_up(cf)
    try:
        wait_health(f"{BASE_URL}/health")
        time.sleep(1)
        fault = run_load_test(BASE_URL, duration=25, concurrency=15,
                               fault_fn=lambda: sh(["docker", "kill", "movie-app-monolith"], check=False),
                               fault_at_s=5)
        save_result("fault_monolith", fault)
    finally:
        compose_down(cf)


# ---------------------------------------------------------------- Experiment 2: orchestration

def run_compose_3x_experiment():
    print("\n=== Experiment 2a: Docker Compose, 3 fixed app replicas behind nginx ===")
    cf = "compose/docker-compose.multi-3x.yml"
    compose_up(cf)
    try:
        startup = wait_health(f"{BASE_URL}/health")
        time.sleep(2)
        cids = compose_container_ids(cf, PROJECT_ROOT)
        stats = docker_stats(cids)
        load = run_load_test(BASE_URL, duration=15, concurrency=30)
        save_result("orchestration_compose_3x", {
            "config": "compose_3x", "startup_time_s": startup, "resources": stats, "load_test": load,
        })

        app1_cid = sh(["docker", "compose", "-f", cf, "ps", "-q", "app1"], cwd=PROJECT_ROOT).stdout.strip()
        fault = run_load_test(BASE_URL, duration=20, concurrency=30,
                               fault_fn=lambda: sh(["docker", "kill", app1_cid], check=False),
                               fault_at_s=5)
        save_result("fault_compose_3x", fault)
    finally:
        compose_down(cf)


def _swarm_active():
    proc = sh(["docker", "info", "--format", "{{.Swarm.LocalNodeState}}"])
    return proc.stdout.strip() == "active"


def _wait_service_replicas(service, n, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        proc = sh(["docker", "service", "ps", service, "--filter", "desired-state=running",
                    "--format", "{{.CurrentState}}"], check=False)
        running = sum(1 for line in proc.stdout.strip().splitlines() if line.startswith("Running"))
        if running >= n:
            return
        time.sleep(1)
    raise TimeoutError(f"{service} did not reach {n} running replicas in {timeout}s")


def _swarm_app_container_ids():
    proc = sh(["docker", "ps", "--filter", "label=com.docker.swarm.service.name=moviestack_app", "-q"])
    return [l.strip() for l in proc.stdout.strip().splitlines() if l.strip()]


def run_swarm_experiment():
    print("\n=== Experiment 2b: Docker Swarm ===")
    if not _swarm_active():
        sh(["docker", "swarm", "init", "--advertise-addr", "127.0.0.1"])

    sh(["docker", "stack", "deploy", "-c", "compose/swarm-stack.yml", "moviestack"], cwd=PROJECT_ROOT)
    try:
        startup = wait_health(f"{BASE_URL}/health", timeout=90)
        time.sleep(2)
        app_cids = _swarm_app_container_ids()
        stats = docker_stats(app_cids)
        load_1x = run_load_test(BASE_URL, duration=15, concurrency=20)
        save_result("orchestration_swarm_1x", {
            "config": "swarm_1x", "startup_time_s": startup, "resources": stats, "load_test": load_1x,
        })

        fault_1x = run_load_test(BASE_URL, duration=20, concurrency=15,
                                  fault_fn=lambda: sh(["docker", "kill", app_cids[0]], check=False),
                                  fault_at_s=5)
        save_result("fault_swarm_1x", fault_1x)

        sh(["docker", "service", "scale", "moviestack_app=3"], cwd=PROJECT_ROOT)
        _wait_service_replicas("moviestack_app", 3)
        time.sleep(2)
        app_cids_3 = _swarm_app_container_ids()
        stats3 = docker_stats(app_cids_3)
        load_3x = run_load_test(BASE_URL, duration=15, concurrency=30)
        save_result("orchestration_swarm_3x", {
            "config": "swarm_3x", "resources": stats3, "load_test": load_3x,
        })

        fault_3x = run_load_test(BASE_URL, duration=20, concurrency=30,
                                  fault_fn=lambda: sh(["docker", "kill", app_cids_3[0]], check=False),
                                  fault_at_s=5)
        save_result("fault_swarm_3x", fault_3x)
    finally:
        sh(["docker", "stack", "rm", "moviestack"], check=False)
        time.sleep(5)


def main():
    run_architecture_experiment()
    run_compose_3x_experiment()
    run_swarm_experiment()
    print("\nAll experiments complete. Raw results in results/raw/.")


if __name__ == "__main__":
    main()
