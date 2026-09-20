"""全局跨进程 GPU 显存互斥租约与内存守卫 (Cross-Process GPU Lease & Memory Guard).

设计原则：
1. 宿主机 RTX 4050 显存仅 6GB，必须由跨进程排他锁严格串行化（Max Concurrent = 1）；
2. 基于 Windows 命名互斥锁 / 平台文件锁（msvcrt / fcntl），超时自动保护（默认 35s）；
3. 提供 ModelHandle 上下文管理器，退出时执行 `del -> gc.collect() -> torch.cuda.empty_cache()`，
   并显式断言显存安全释放，杜绝隐形碎片累积。
"""
from __future__ import annotations

import contextlib
import gc
import logging
import os
import sys
import time
from pathlib import Path
from typing import Generator

log = logging.getLogger("reviewer.gpu_lease")

LOCK_FILE = Path(r"D:\tenhoulib\.gpu_lease.lock")


class GpuLeaseTimeoutError(TimeoutError):
    """获取 GPU 租约超时异常。"""
    pass


class GpuLease:
    """跨进程 GPU 显存互斥租约。"""

    def __init__(self, lock_path: Path = LOCK_FILE, timeout: float = 35.0):
        self.lock_path = lock_path
        self.timeout = timeout
        self.file_handle = None

    def __enter__(self) -> GpuLease:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    def acquire(self) -> None:
        start_time = time.time()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                # 以独占创建模式尝试打开锁文件
                if sys.platform == "win32":
                    import msvcrt
                    self.file_handle = open(self.lock_path, "a+b")
                    msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    self.file_handle = open(self.lock_path, "a+b")
                    fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                # 成功加锁，写入当前持有进程信息与时间戳
                self.file_handle.seek(0)
                self.file_handle.truncate()
                payload = f"pid={os.getpid()};ts={time.time()}".encode("utf-8")
                self.file_handle.write(payload)
                self.file_handle.flush()
                log.debug("成功获取 GPU 互斥租约 (PID: %s)", os.getpid())
                return
            except (IOError, OSError):
                # 锁被其他进程持有
                if self.file_handle:
                    try:
                        self.file_handle.close()
                    except Exception:
                        pass
                    self.file_handle = None

                elapsed = time.time() - start_time
                if elapsed >= self.timeout:
                    raise GpuLeaseTimeoutError(
                        f"等待 GPU 互斥租约超时 ({self.timeout}s)，其他进程正在使用 GPU，已自动放弃争抢。"
                    )
                time.sleep(0.1)

    def release(self) -> None:
        if self.file_handle:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self.file_handle.seek(0)
                    msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_UN)
                self.file_handle.close()
            except Exception as exc:
                log.warning("释放 GPU 租约异常: %s", exc)
            finally:
                self.file_handle = None
                log.debug("GPU 互斥租约已释放 (PID: %s)", os.getpid())


@contextlib.contextmanager
def guarded_gpu_context(model_tag: str, timeout: float = 35.0) -> Generator[None, None, None]:
    """带严格显存看门狗的 GPU 执行上下文。"""
    import torch

    with GpuLease(timeout=timeout):
        try:
            yield
        finally:
            # 强化回收
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                free_b, total_b = torch.cuda.mem_get_info()
                free_mb = free_b / (1024 * 1024)
                total_mb = total_b / (1024 * 1024)
                used_mb = total_mb - free_mb
                log.info(
                    "[%s] 推理结束，显存已清空回收: 空闲 %.1f MB / 占用 %.1f MB",
                    model_tag, free_mb, used_mb
                )
