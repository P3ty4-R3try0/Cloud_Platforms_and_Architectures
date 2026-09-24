"""Re-runs just the fault-injection tests with a shorter per-request timeout
and longer durations for the single-replica configs, so recovery is actually
observed within the test window instead of just showing "still down at the
end". Overwrites the corresponding results/raw/fault_*.json files.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from docker_utils import sh, wait_health
from load_test import run_load_test
from run_experiments import (
    PROJECT_ROOT, BASE_URL, compose_up, compose_down, save_result,
    _swarm_active, _wait_service_replicas, _swarm_app_container_ids,
)


def fault_monolith():
    cf = "compose/docker-compose.monolith.yml"
    compose_up(cf, build=False)
    try:
        wait_health(f"{BASE_URL}/health")
        time.sleep(1)
        result = run_load_test(BASE_URL, duration=40, concurrency=15,
                                fault_fn=lambda: sh(["docker", "kill", "movie-app-monolith"], check=False),
                                fault_at_s=5)
        save_result("fault_monolith", result)
        print("monolith recovery_time_s:", result["recovery_time_s"])
    finally:
        compose_down(cf)


def fault_compose_1x():
    cf = "compose/docker-compose.multi.yml"
    compose_up(cf, build=False)
    try:
        wait_health(f"{BASE_URL}/health")
        time.sleep(1)
        result = run_load_test(BASE_URL, duration=35, concurrency=15,
                                fault_fn=lambda: sh(["docker", "kill", "movie-app-multi"], check=False),
                                fault_at_s=5)
        save_result("fault_compose_1x", result)
        print("compose_1x recovery_time_s:", result["recovery_time_s"])
    finally:
        compose_down(cf)


def fault_compose_3x():
    cf = "compose/docker-compose.multi-3x.yml"
    compose_up(cf, build=False)
    try:
        wait_health(f"{BASE_URL}/health")
        time.sleep(2)
        app1_cid = sh(["docker", "compose", "-f", cf, "ps", "-q", "app1"], cwd=PROJECT_ROOT).stdout.strip()
        result = run_load_test(BASE_URL, duration=20, concurrency=30,
                                fault_fn=lambda: sh(["docker", "kill", app1_cid], check=False),
                                fault_at_s=5)
        save_result("fault_compose_3x", result)
        print("compose_3x recovery_time_s:", result["recovery_time_s"])
    finally:
        compose_down(cf)


def fault_swarm():
    if not _swarm_active():
        sh(["docker", "swarm", "init", "--advertise-addr", "127.0.0.1"])
    sh(["docker", "stack", "deploy", "-c", "compose/swarm-stack.yml", "moviestack"], cwd=PROJECT_ROOT)
    try:
        wait_health(f"{BASE_URL}/health", timeout=90)
        time.sleep(2)
        app_cids = _swarm_app_container_ids()
        result_1x = run_load_test(BASE_URL, duration=35, concurrency=15,
                                   fault_fn=lambda: sh(["docker", "kill", app_cids[0]], check=False),
                                   fault_at_s=5)
        save_result("fault_swarm_1x", result_1x)
        print("swarm_1x recovery_time_s:", result_1x["recovery_time_s"])

        sh(["docker", "service", "scale", "moviestack_app=3"], cwd=PROJECT_ROOT)
        _wait_service_replicas("moviestack_app", 3)
        time.sleep(2)
        app_cids_3 = _swarm_app_container_ids()
        result_3x = run_load_test(BASE_URL, duration=20, concurrency=30,
                                   fault_fn=lambda: sh(["docker", "kill", app_cids_3[0]], check=False),
                                   fault_at_s=5)
        save_result("fault_swarm_3x", result_3x)
        print("swarm_3x recovery_time_s:", result_3x["recovery_time_s"])
    finally:
        sh(["docker", "stack", "rm", "moviestack"], check=False)
        time.sleep(5)


if __name__ == "__main__":
    fault_monolith()
    fault_compose_1x()
    fault_compose_3x()
    fault_swarm()
    print("done")
