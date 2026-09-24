import json
import subprocess
import time
import urllib.request
import urllib.error


def sh(cmd, cwd=None, check=True):
    print(f"$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.returncode != 0:
        print(proc.stderr.strip())
        if check:
            raise RuntimeError(f"command failed: {' '.join(cmd)}")
    return proc


def wait_health(url, timeout=90, interval=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return time.time() - t0
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(interval)
    raise TimeoutError(f"{url} did not become healthy within {timeout}s")


def docker_stats(container_ids, sample_seconds=3):
    """Averages docker stats over a short sampling window."""
    if not container_ids:
        return {}
    samples = {cid: [] for cid in container_ids}
    n_samples = max(1, sample_seconds)
    for _ in range(n_samples):
        proc = sh(["docker", "stats", "--no-stream", "--format",
                    "{{.ID}}|{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"] + container_ids, check=False)
        for line in proc.stdout.strip().splitlines():
            parts = line.split("|")
            if len(parts) != 4:
                continue
            cid, name, cpu, mem = parts
            cpu_val = float(cpu.strip().rstrip("%") or 0)
            mem_used = mem.split("/")[0].strip()
            mem_mb = _to_mb(mem_used)
            samples.setdefault(cid, []).append((name, cpu_val, mem_mb))
        time.sleep(1)

    result = {}
    for cid, entries in samples.items():
        if not entries:
            continue
        name = entries[0][0]
        avg_cpu = sum(e[1] for e in entries) / len(entries)
        avg_mem = sum(e[2] for e in entries) / len(entries)
        result[name] = {"cpu_percent": avg_cpu, "mem_mb": avg_mem}
    return result


def _to_mb(s):
    s = s.strip()
    try:
        if s.endswith("GiB"):
            return float(s[:-3]) * 1024
        if s.endswith("MiB"):
            return float(s[:-3])
        if s.endswith("KiB"):
            return float(s[:-3]) / 1024
        if s.endswith("B"):
            return float(s[:-1]) / (1024 * 1024)
    except ValueError:
        return 0.0
    return 0.0


def image_size_mb(image):
    proc = sh(["docker", "image", "inspect", image, "--format", "{{.Size}}"])
    size_bytes = int(proc.stdout.strip().splitlines()[0])
    return size_bytes / (1024 * 1024)


def compose_container_ids(compose_file, project_dir):
    proc = sh(["docker", "compose", "-f", compose_file, "ps", "-q"], cwd=project_dir)
    return [line.strip() for line in proc.stdout.strip().splitlines() if line.strip()]
