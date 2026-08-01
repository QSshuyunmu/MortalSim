from __future__ import annotations

import json
import multiprocessing as mp
import queue
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .gpu_monitor import GpuMonitor
from .service import worker_main


class MortalApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Mortal 自亲第一打模拟器")
        self.root.geometry("1080x720")
        self.root.minsize(900, 620)
        self.process: mp.Process | None = None
        self.events: mp.Queue | None = None
        self.result: dict[str, Any] | None = None
        self.started_at = 0.0
        self.total_steps = 1
        self.completed_steps = 0
        self.gpu_monitor: GpuMonitor | None = None
        self.gpu_summary: dict[str, Any] | None = None
        self.gpu_events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.gpu_status = tk.StringVar(value="GPU: 未监测")
        self._last_gpu_level = "normal"
        self._build()

    def _build(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        controls = ttk.LabelFrame(root, text="分析参数", padding=12)
        controls.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        for column in range(6):
            controls.columnconfigure(column, weight=1 if column in (1, 3, 5) else 0)

        self.vars = {
            "hand": tk.StringVar(value="4567m3477p13406s"),
            "first_tsumo": tk.StringVar(value="6s"),
            "dora": tk.StringVar(value="9s"),
            "discards": tk.StringVar(value="1s,6s"),
            "runs": tk.StringVar(value="1000"),
            "seed": tk.StringVar(value="42"),
            "oya": tk.StringVar(value="0"),
            "batch_size": tk.StringVar(value="1000"),
            "rayon_threads": tk.StringVar(value="20"),
        }
        fields = [
            ("手牌", "hand", 0, 0, 3),
            ("第一摸牌", "first_tsumo", 0, 4, 1),
            ("宝牌指示", "dora", 0, 6, 1),
            ("第一打候选", "discards", 1, 0, 3),
            ("模拟局数", "runs", 1, 4, 1),
            ("Seed", "seed", 1, 6, 1),
            ("亲家座位", "oya", 2, 0, 1),
            ("每批局数", "batch_size", 2, 2, 1),
            ("Rayon 线程", "rayon_threads", 2, 4, 1),
        ]
        for label, key, row, column, span in fields:
            ttk.Label(controls, text=label).grid(row=row, column=column, sticky="w", padx=(0, 6), pady=4)
            ttk.Entry(controls, textvariable=self.vars[key], width=18).grid(
                row=row, column=column + 1, columnspan=span, sticky="ew", padx=(0, 14), pady=4
            )

        actions = ttk.Frame(controls)
        actions.grid(row=2, column=6, columnspan=2, sticky="e", pady=4)
        self.start_button = ttk.Button(actions, text="开始分析", command=self.start)
        self.start_button.pack(side="left", padx=(0, 6))
        self.stop_button = ttk.Button(actions, text="取消", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=(0, 6))
        self.export_button = ttk.Button(actions, text="导出 JSON", command=self.export, state="disabled")
        self.export_button.pack(side="left")

        body = ttk.Frame(root, padding=(12, 0, 12, 12))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(1, weight=1)

        self.status = tk.StringVar(value="就绪")
        status_line = ttk.Frame(body)
        status_line.grid(row=0, column=0, sticky="w", pady=(0, 5))
        ttk.Label(status_line, textvariable=self.status).pack(side="left")
        ttk.Label(status_line, textvariable=self.gpu_status).pack(side="left", padx=(18, 0))
        self.progress = ttk.Progressbar(body, mode="determinate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=(0, 5))

        result_frame = ttk.LabelFrame(body, text="结果", padding=8)
        result_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        columns = ("discard", "games", "error", "hora", "tsumo", "draw", "agari", "houjuu", "rank", "point")
        self.table = ttk.Treeview(result_frame, columns=columns, show="headings", height=10)
        headings = {
            "discard": "第一打", "games": "局数", "error": "错误", "hora": "荣和",
            "tsumo": "自摸", "draw": "流局", "agari": "和了率", "houjuu": "放铳率",
            "rank": "平均顺位", "point": "平均得点",
        }
        widths = {"discard": 70, "games": 70, "error": 60, "hora": 60, "tsumo": 60, "draw": 60,
                  "agari": 80, "houjuu": 80, "rank": 80, "point": 90}
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], anchor="center")
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.table.configure(yscrollcommand=scrollbar.set)

        log_frame = ttk.LabelFrame(body, text="运行信息", padding=8)
        log_frame.grid(row=1, column=1, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, wrap="word", state="disabled", width=42)
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)

    def _append_log(self, message: str):
        self.log.configure(state="normal")
        self.log.insert("end", f"{message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _request(self) -> dict[str, Any]:
        return {key: variable.get().strip() for key, variable in self.vars.items()}

    def start(self):
        if self.process is not None and self.process.is_alive():
            return
        request = self._request()
        try:
            runs = int(request["runs"])
            batch = int(request["batch_size"])
            candidates = [value.strip() for value in request["discards"].split(",") if value.strip()]
            if runs < 1 or batch < 1 or not candidates:
                raise ValueError("局数、每批局数和候选牌不能为空")
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self.result = None
        self.gpu_summary = None
        self._last_gpu_level = "normal"
        self.completed_steps = 0
        self.total_steps = len(candidates) * ((runs + batch - 1) // batch)
        self.progress.configure(maximum=self.total_steps, value=0)
        self.status.set("正在启动 Worker...")
        self._append_log(f"开始: {', '.join(candidates)} / {runs} 局")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.export_button.configure(state="disabled")
        self.started_at = time.perf_counter()
        self.events = mp.Queue()
        telemetry_name = f"gpu_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.csv"
        self.gpu_monitor = GpuMonitor(
            self.gpu_events.put,
            Path(__file__).resolve().parents[1] / "results" / telemetry_name,
        )
        self.gpu_monitor.start()
        self.process = mp.Process(target=worker_main, args=(request, self.events), daemon=True)
        self.process.start()
        self.root.after(100, self.poll)

    def stop(self):
        self._stop_gpu_monitor()
        if self.process is None:
            return
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
        self.process = None
        self.status.set("已取消")
        self._append_log("任务已取消")
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def poll(self):
        if self.events is None:
            return
        self._drain_gpu_events()
        try:
            while True:
                event = self.events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        if self.process is not None and self.process.is_alive():
            self.root.after(100, self.poll)
        elif self.process is not None and self.result is None:
            self._stop_gpu_monitor()
            self.status.set("Worker 已退出")
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")

    def _drain_gpu_events(self):
        try:
            while True:
                self._handle_gpu_status(self.gpu_events.get_nowait())
        except queue.Empty:
            return

    def _handle_gpu_status(self, event: dict[str, Any]):
        if not event.get("available"):
            self.gpu_status.set("GPU: nvidia-smi 不可用")
            return
        sample = event["sample"]
        temp = sample.get("temperature.gpu")
        util = sample.get("utilization.gpu")
        memory = sample.get("memory.used")
        total = sample.get("memory.total")
        temp_text = f"{temp:.0f}°C" if temp is not None else "--"
        util_text = f"{util:.0f}%" if util is not None else "--"
        memory_text = (
            f"{memory:.0f}/{total:.0f} MiB"
            if memory is not None and total is not None else "--"
        )
        self.gpu_status.set(
            f"GPU: {temp_text} | {util_text} | VRAM {memory_text}"
        )
        level = event.get("level", "normal")
        if level in ("warning", "critical") and level != self._last_gpu_level:
            self._append_log(f"GPU {event['level']}: {event.get('message', '')}")
        self._last_gpu_level = level

    def _handle_event(self, event: dict[str, Any]):
        kind = event.get("type")
        if kind == "gpu_status":
            self._handle_gpu_status(event)
        elif kind == "status":
            self.status.set(event["message"])
            self._append_log(event["message"])
        elif kind == "candidate_started":
            self.status.set(f"正在分析 {event['discard']} ({event['index'] + 1}/{event['total']})")
        elif kind == "batch_completed":
            self.completed_steps += 1
            self.progress.configure(value=self.completed_steps)
            self.status.set(
                f"{event['discard']}: {event['completed']}/{event['total']} 局"
            )
        elif kind == "candidate_completed":
            summary = event["summary"]
            self._append_log(
                f"{summary['discard']} 完成: 和了 {summary['agari_rate']:.1%}, "
                f"平均顺位 {summary['avg_rank']:.3f}"
            )
        elif kind == "completed":
            self._stop_gpu_monitor()
            self.result = event["result"]
            self.result["gpu_telemetry"] = self.gpu_summary
            self.render_result(self.result)
            self.status.set(f"完成，总耗时 {self.result['elapsed']:.1f}s")
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.export_button.configure(state="normal")
            self.process = None
        elif kind == "failed":
            self._stop_gpu_monitor()
            self.status.set("运行失败")
            self._append_log(event.get("traceback", event.get("error", "未知错误")))
            messagebox.showerror("运行失败", event.get("error", "未知错误"))
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.process = None

    def render_result(self, result: dict[str, Any]):
        for item in self.table.get_children():
            self.table.delete(item)
        for summary in result["summaries"]:
            self.table.insert("", "end", values=(
                summary["discard"], summary["games"], summary["errors"], summary["hora"],
                summary["tsumo"], summary["ryukyoku"], f"{summary['agari_rate']:.2%}",
                f"{summary['houjuu_rate']:.2%}", f"{summary['avg_rank']:.3f}",
                f"{summary['avg_point']:+.1f}",
            ))
        for comparison in result["comparisons"]:
            self._append_log(
                f"相对 {comparison['discard']}: 平均得点差 "
                f"{comparison['paired_point_delta']:+.1f}, "
                f"95% CI [{comparison['ci95'][0]:+.1f}, {comparison['ci95'][1]:+.1f}]"
            )

    def export(self):
        if self.result is None:
            return
        path = filedialog.asksaveasfilename(
            title="导出分析结果",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        Path(path).write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding="utf-8")
        self._append_log(f"已导出: {path}")

    def _stop_gpu_monitor(self):
        if self.gpu_monitor is None:
            return
        self.gpu_monitor.stop()
        summary = self.gpu_monitor.summary()
        self.gpu_summary = summary
        if summary["available"]:
            temp_range = (
                f"{summary['temperature_min']:.0f}-{summary['temperature_max']:.0f}°C"
                if summary["temperature_min"] is not None else "--"
            )
            memory_peak = (
                f"{summary['memory_used_max_mib']:.0f} MiB"
                if summary["memory_used_max_mib"] is not None else "--"
            )
            self._append_log(
                f"GPU 监测: {summary['sample_count']} samples, "
                f"温度 {temp_range}, 显存峰值 {memory_peak}, "
                f"日志 {summary['telemetry_path']}"
            )
        self.gpu_status.set("GPU: 监测已停止")
        self.gpu_monitor = None

    def close(self):
        self.stop()
        self.root.destroy()


def main():
    mp.freeze_support()
    root = tk.Tk()
    app = MortalApp(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
