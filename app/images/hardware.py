"""Conservative resource detection including container memory limits."""

import os
from pathlib import Path
import platform


def hardware():
    info = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            info[key] = int(value.strip().split()[0]) * 1024
    except (OSError, ValueError):
        pass
    available = info.get("MemAvailable", 0)
    total = info.get("MemTotal", 0)
    try:
        limit = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        used = int(Path("/sys/fs/cgroup/memory.current").read_text())
        if limit != "max":
            total = min(total or int(limit), int(limit))
            available = min(available or int(limit), max(0, int(limit) - used))
    except (OSError, ValueError):
        pass
    try:
        text = Path("/proc/cpuinfo").read_text()
        model = next(
            line.split(":", 1)[1].strip()
            for line in text.splitlines()
            if line.startswith("model name")
        )
        flags = next(
            line.split(":", 1)[1].split()
            for line in text.splitlines()
            if line.startswith("flags")
        )
    except (OSError, StopIteration):
        model = platform.processor()
        flags = []
    cpus = (
        len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else os.cpu_count() or 1
    )
    return {
        "cpu": model,
        "logical_cpus": cpus,
        "avx2": "avx2" in flags,
        "ram_bytes": total,
        "available_bytes": available,
        "architecture": platform.machine(),
    }


def check(settings, detected=None):
    detected = detected or hardware()
    required = 8 * 1024**3 * max(1, (settings["resolution"] / 512) ** 2)
    if detected["available_bytes"] < required:
        raise RuntimeError(
            f"Insufficient available RAM: {detected['available_bytes'] / 1024**3:.1f} GiB; plan for at least {required / 1024**3:.0f} GiB available. Use 512 pixels, close other workloads or add RAM; no cloud fallback."
        )
    return detected
