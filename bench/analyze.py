import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS_RAW = os.path.join(os.path.dirname(__file__), "..", "results", "raw")
FIG_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "figures")
SUMMARY_CSV = os.path.join(os.path.dirname(__file__), "..", "results", "summary.csv")

CONFIGS = ["monolith", "multi", "compose_3x", "swarm_1x", "swarm_3x"]
COLORS = {
    "monolith": "#2a78d6",
    "multi": "#eb6834",
    "compose_3x": "#1baf7a",
    "swarm_1x": "#eda100",
    "swarm_3x": "#e87ba4",
}
LABELS = {
    "monolith": "Μονολιθικό\n(1 container)",
    "multi": "Compose\n(app+redis, 1x)",
    "compose_3x": "Compose\n(3x + nginx)",
    "swarm_1x": "Swarm\n(1 replica)",
    "swarm_3x": "Swarm\n(3 replicas)",
}

TEXT_PRIMARY = "#0b0b0b"
TEXT_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
    "axes.edgecolor": AXIS, "axes.labelcolor": TEXT_PRIMARY, "text.color": TEXT_PRIMARY,
    "xtick.color": TEXT_MUTED, "ytick.color": TEXT_MUTED, "font.size": 11,
    "axes.spines.top": False, "axes.spines.right": False, "grid.color": GRID,
})


def load(name):
    path = os.path.join(RESULTS_RAW, f"{name}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def bar_chart(configs, values, ylabel, title, filename, value_fmt="{:.1f}"):
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150)
    xs = range(len(configs))
    colors = [COLORS[c] for c in configs]
    bars = ax.bar(xs, values, color=colors, width=0.6)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([LABELS[c] for c in configs], fontsize=9)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontsize=12)
    ax.grid(True, axis="y", linewidth=0.8)
    ax.set_axisbelow(True)
    for b, v in zip(bars, values):
        ax.annotate(value_fmt.format(v), (b.get_x() + b.get_width() / 2, b.get_height()),
                    ha="center", va="bottom", fontsize=9, color=TEXT_PRIMARY)
    fig.tight_layout()
    out = os.path.join(FIG_DIR, filename)
    fig.savefig(out)
    plt.close(fig)
    print(f"saved {out}")


def fault_recovery_chart(fault_results, filename):
    fig, ax = plt.subplots(figsize=(7.2, 4.4), dpi=150)
    for label, data in fault_results.items():
        per_sec = data["per_second"]
        xs = [p["second"] for p in per_sec]
        ys = [p["error_rate"] * 100 for p in per_sec]
        ax.plot(xs, ys, marker="o", markersize=4, linewidth=2, color=COLORS[label], label=LABELS[label].replace("\n", " "))
    ax.axvline(5, color=TEXT_MUTED, linestyle="--", linewidth=1)
    ax.annotate("έγχυση σφάλματος", (5, ax.get_ylim()[1] * 0.9), fontsize=9, color=TEXT_MUTED)
    ax.set_xlabel("Δευτερόλεπτα εντός της δοκιμής φόρτου")
    ax.set_ylabel("Ποσοστό σφαλμάτων (%)")
    ax.set_title("Συμπεριφορά ανάκαμψης μετά τον τερματισμό ενός backend container", loc="left", fontsize=12)
    ax.grid(True, axis="y", linewidth=0.8)
    ax.legend(frameon=False, loc="upper right", fontsize=9)
    fig.tight_layout()
    out = os.path.join(FIG_DIR, filename)
    fig.savefig(out)
    plt.close(fig)
    print(f"saved {out}")


def main():
    os.makedirs(FIG_DIR, exist_ok=True)

    arch = {"monolith": load("architecture_monolith"), "multi": load("architecture_multi")}
    orch = {
        "compose_3x": load("orchestration_compose_3x"),
        "swarm_1x": load("orchestration_swarm_1x"),
        "swarm_3x": load("orchestration_swarm_3x"),
    }
    faults = {
        "monolith": load("fault_monolith"),
        "multi": load("fault_compose_1x"),
        "compose_3x": load("fault_compose_3x"),
        "swarm_1x": load("fault_swarm_1x"),
        "swarm_3x": load("fault_swarm_3x"),
    }

    if arch["monolith"] and arch["multi"]:
        bar_chart(["monolith", "multi"],
                   [arch["monolith"]["image_size_mb"], arch["multi"]["image_size_mb"]],
                   "Μέγεθος εικόνας (MB)",
                   "Μέγεθος εικόνας container: μονολιθική vs πολυ-container εικόνα",
                   "image_size.png")

    startup_configs, startup_vals = [], []
    for c in CONFIGS:
        d = arch.get(c) or orch.get(c)
        if d and "startup_time_s" in d:
            startup_configs.append(c)
            startup_vals.append(d["startup_time_s"])
    if startup_configs:
        bar_chart(startup_configs, startup_vals, "Χρόνος έως την ετοιμότητα (s)",
                   "Χρόνος εκκίνησης / ανάπτυξης έως την πρώτη υγιή απόκριση",
                   "startup_time.png", value_fmt="{:.2f}")

    tput_configs, tput_vals = [], []
    lat_configs, lat_p95 = [], []
    for c in CONFIGS:
        d = arch.get(c) or orch.get(c)
        if d and "load_test" in d:
            tput_configs.append(c)
            tput_vals.append(d["load_test"]["throughput_rps"])
            lat_configs.append(c)
            lat_p95.append(d["load_test"]["p95_ms"])
    if tput_configs:
        bar_chart(tput_configs, tput_vals, "Throughput (αιτήματα/δευτ.)",
                   "Βασικό throughput δοκιμής φόρτου ανά διαμόρφωση",
                   "throughput.png", value_fmt="{:.1f}")
    if lat_configs:
        bar_chart(lat_configs, lat_p95, "Καθυστέρηση p95 (ms)",
                   "Βασική καθυστέρηση p95 δοκιμής φόρτου ανά διαμόρφωση",
                   "latency_p95.png", value_fmt="{:.1f}")

    mem_configs, mem_vals = [], []
    for c in CONFIGS:
        d = arch.get(c) or orch.get(c)
        if d and "resources" in d and d["resources"]:
            total_mem = sum(v["mem_mb"] for v in d["resources"].values())
            mem_configs.append(c)
            mem_vals.append(total_mem)
    if mem_configs:
        bar_chart(mem_configs, mem_vals, "Συνολική μνήμη (MB)",
                   "Συνολική χρήση μνήμης containers ανά διαμόρφωση",
                   "resource_usage.png", value_fmt="{:.0f}")

    available_faults = {k: v for k, v in faults.items() if v}
    if available_faults:
        fault_recovery_chart(available_faults, "fault_recovery.png")

    rec_configs = [c for c in CONFIGS if faults.get(c)]
    if rec_configs:
        NO_RECOVERY_MARKER = max(
            (f["recovery_time_s"] for f in available_faults.values() if f["recovery_time_s"]),
            default=1.0,
        ) * 1.3
        rec_vals = [faults[c]["recovery_time_s"] if faults[c]["recovery_time_s"] is not None
                    else NO_RECOVERY_MARKER for c in rec_configs]
        fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150)
        bars = ax.bar(range(len(rec_configs)), rec_vals, color=[COLORS[c] for c in rec_configs], width=0.6)
        ax.set_xticks(range(len(rec_configs)))
        ax.set_xticklabels([LABELS[c] for c in rec_configs], fontsize=9)
        ax.set_ylabel("Χρόνος ανάκαμψης (s)")
        ax.set_title("Χρόνος ανάκαμψης μετά τον τερματισμό ενός backend container", loc="left", fontsize=12)
        ax.grid(True, axis="y", linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_ylim(0, NO_RECOVERY_MARKER * 1.18)
        for b, c in zip(bars, rec_configs):
            if faults[c]["recovery_time_s"] is None:
                ax.annotate("καμία\nανάκαμψη", (b.get_x() + b.get_width() / 2, b.get_height()),
                            ha="center", va="top", fontsize=9, color="white",
                            xytext=(0, -8), textcoords="offset points")
            else:
                ax.annotate(f"{faults[c]['recovery_time_s']:.2f}s", (b.get_x() + b.get_width() / 2, b.get_height()),
                            ha="center", va="bottom", fontsize=9, color=TEXT_PRIMARY)
        fig.tight_layout()
        out = os.path.join(FIG_DIR, "recovery_time.png")
        fig.savefig(out)
        plt.close(fig)
        print(f"saved {out}")

    # --- Summary CSV ---
    rows = []
    for c in CONFIGS:
        d = arch.get(c) or orch.get(c)
        f = faults.get(c)
        row = {"config": c}
        if d:
            row["startup_time_s"] = d.get("startup_time_s")
            row["image_size_mb"] = d.get("image_size_mb")
            if "load_test" in d:
                row["throughput_rps"] = d["load_test"]["throughput_rps"]
                row["p50_ms"] = d["load_test"]["p50_ms"]
                row["p95_ms"] = d["load_test"]["p95_ms"]
            if "resources" in d and d["resources"]:
                row["total_mem_mb"] = sum(v["mem_mb"] for v in d["resources"].values())
        if f:
            row["fault_errors"] = f["errors"]
            row["fault_error_rate_pct"] = 100 * f["errors"] / f["requests"] if f["requests"] else None
            row["recovery_time_s"] = f["recovery_time_s"]
        rows.append(row)

    fieldnames = sorted({k for r in rows for k in r})
    with open(SUMMARY_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"saved {SUMMARY_CSV}")
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
