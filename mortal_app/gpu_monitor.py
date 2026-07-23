"""Low-overhead NVIDIA GPU telemetry for the desktop runner.

The monitor deliberately runs outside the simulation worker. It only reads
``nvidia-smi`` and therefore cannot change Rust ordering, AMP batch shapes, or
the action stream used by a run.
"""

from __future__ import annotations

import csv
import io
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


QUERY_FIELDS = (
    "temperature.gpu",
    "utilization.gpu",
    "memory.used",
    "memory.total",
    "power.draw",
    "power.limit",
    "clocks.current.graphics",
)


def _number(value: str) -> float | None:
    value = value.strip()
    if not value or value.upper() == "N/A":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_nvidia_smi_line(line: str) -> dict[str, Any] | None:
    """Parse one ``nvidia-smi --format=csv,noheader,nounits`` row."""
    values = next(csv.reader(io.StringIO(line)), [])
    if len(values) != len(QUERY_FIELDS):
        return None
    sample: dict[str, Any] = {"timestamp": datetime.now().isoformat(timespec="seconds")}
    for field, value in zip(QUERY_FIELDS, values):
        sample[field] = _number(value)
    return sample


def query_gpu() -> dict[str, Any] | None:
    command = [
        "nvidia-smi",
        f"--query-gpu={','.join(QUERY_FIELDS)}",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        sample = parse_nvidia_smi_line(line)
        if sample is not None:
            return sample
    return None


def assess_sample(sample: dict[str, Any]) -> tuple[str, str]:
    temperature = sample.get("temperature.gpu")
    memory_used = sample.get("memory.used")
    memory_total = sample.get("memory.total")
    if temperature is not None and temperature >= 90:
        return "critical", f"GPU 温度 {temperature:.0f}°C，已达到保护阈值"
    if (
        memory_used is not None
        and memory_total
        and memory_used / memory_total >= 0.95
    ):
        return "critical", f"GPU 显存 {memory_used:.0f}/{memory_total:.0f} MiB，接近耗尽"
    if temperature is not None and temperature >= 85:
        return "warning", f"GPU 温度 {temperature:.0f}°C"
    if (
        memory_used is not None
        and memory_total
        and memory_used / memory_total >= 0.90
    ):
        return "warning", f"GPU 显存使用率 {memory_used / memory_total:.0%}"
    return "normal", ""


class GpuMonitor:
    def __init__(
        self,
        emit: Callable[[dict[str, Any]], None],
        output_path: Path,
        interval: float = 2.0,
    ):
        self.emit = emit
        self.output_path = output_path
        self.interval = max(interval, 0.5)
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._file = None
        self._writer = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.output_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file,
            fieldnames=("timestamp", *QUERY_FIELDS),
        )
        self._writer.writeheader()
        self._file.flush()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mortal-gpu-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = query_gpu()
            if sample is None:
                self.emit({"type": "gpu_status", "available": False})
            else:
                self.samples.append(sample)
                if self._writer is not None:
                    self._writer.writerow(sample)
                    if self._file is not None:
                        self._file.flush()
                level, message = assess_sample(sample)
                self.emit({
                    "type": "gpu_status",
                    "available": True,
                    "sample": sample,
                    "level": level,
                    "message": message,
                })
            self._stop.wait(self.interval)

    def summary(self) -> dict[str, Any]:
        temperatures = [s["temperature.gpu"] for s in self.samples if s.get("temperature.gpu") is not None]
        memory = [s["memory.used"] for s in self.samples if s.get("memory.used") is not None]
        power = [s["power.draw"] for s in self.samples if s.get("power.draw") is not None]
        levels = [assess_sample(sample)[0] for sample in self.samples]
        return {
            "available": bool(self.samples),
            "sample_count": len(self.samples),
            "temperature_min": min(temperatures) if temperatures else None,
            "temperature_max": max(temperatures) if temperatures else None,
            "temperature_avg": sum(temperatures) / len(temperatures) if temperatures else None,
            "memory_used_max_mib": max(memory) if memory else None,
            "power_draw_max_w": max(power) if power else None,
            "warning_samples": levels.count("warning"),
            "critical_samples": levels.count("critical"),
            "telemetry_path": str(self.output_path),
        }
