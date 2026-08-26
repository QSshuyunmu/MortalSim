"""MortalSim 本地 API 客户端（异步）。"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx


class MortalSimError(RuntimeError):
    pass


class MortalClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(trust_env=False, timeout=self.timeout)
        return self._client

    async def health(self) -> dict:
        client = await self._http()
        resp = await client.get(f"{self.base}/api/health")
        resp.raise_for_status()
        return resp.json()

    async def get_active_runs(self) -> list[str]:
        """查询 MortalSim 当前仍在排队/运行中的任务 run_id 列表。"""
        client = await self._http()
        resp = await client.get(f"{self.base}/api/tasks/active")
        if resp.status_code != 200:
            raise MortalSimError(f"查询活跃任务失败 HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return [str(item.get("run_id")) for item in data if item.get("run_id")]

    async def _wait_until_free(self, deadline: float, poll_seconds: float = 4.0) -> None:
        """持续等待 MortalSim 空闲（不再有排队/运行任务）。"""
        loop = asyncio.get_event_loop()
        while loop.time() < deadline:
            if not await self.get_active_runs():
                return
            await asyncio.sleep(poll_seconds)
        raise MortalSimError("等待 MortalSim 空闲超时，仍有其他模拟在运行")

    async def create_run(
        self,
        request: dict[str, Any],
        *,
        max_wait_seconds: float = 900.0,
        poll_seconds: float = 4.0,
    ) -> str:
        """创建模拟任务；若遇到“同时只能跑一个”(503) 则等待空闲后自动重试，不直接失败。"""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + max_wait_seconds
        while True:
            client = await self._http()
            resp = await client.post(f"{self.base}/api/runs", json=request)
            if resp.status_code in (200, 201, 202):
                data = resp.json()
                run_id = data.get("run_id")
                if not run_id:
                    raise MortalSimError(f"响应缺少 run_id: {data}")
                return run_id
            if resp.status_code == 503 and "only one simulation can run at a time" in resp.text:
                if loop.time() >= deadline:
                    raise MortalSimError("创建任务失败：MortalSim 持续忙（仍有其他模拟在运行），已等待超时")
                await self._wait_until_free(deadline, poll_seconds)
                continue
            raise MortalSimError(f"创建任务失败 HTTP {resp.status_code}: {resp.text[:300]}")

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        client = await self._http()
        resp = await client.post(f"{self.base}/api/runs/{run_id}/cancel")
        if resp.status_code != 200:
            raise MortalSimError(f"取消任务失败 HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def get_run(self, run_id: str) -> dict[str, Any]:
        client = await self._http()
        resp = await client.get(f"{self.base}/api/runs/{run_id}")
        if resp.status_code != 200:
            raise MortalSimError(f"查询任务失败 HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def wait_completed(self, run_id: str, timeout_seconds: float = 0, poll_seconds: float = 2.0) -> dict[str, Any]:
        has_deadline = timeout_seconds > 0
        deadline = asyncio.get_event_loop().time() + timeout_seconds if has_deadline else float("inf")
        while True:
            job = await self.get_run(run_id)
            status = job.get("status")
            if status == "completed":
                return job
            if status in ("failed", "cancelled"):
                raise MortalSimError(f"任务 {status}: {job.get('error') or job.get('diagnostic_log') or '未知错误'}")
            if has_deadline and asyncio.get_event_loop().time() > deadline:
                raise MortalSimError(f"任务超时（>{timeout_seconds:.0f}s）")
            await asyncio.sleep(poll_seconds)
