"""riichi-vision OCR 客户端：上传截图 → confirm → tenhou/6 JSON。"""
from __future__ import annotations

from typing import Any

import httpx


class OcrError(RuntimeError):
    pass


class OcrClient:
    def __init__(self, base_url: str, timeout: float = 60.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(trust_env=False, timeout=self.timeout)
        return self._client

    async def upload_image(self, image_path: str, filename: str | None = None) -> str:
        client = await self._http()
        name = filename or "screenshot.png"
        with open(image_path, "rb") as f:
            files = {"file": (name, f, "image/png")}
            resp = await client.post(f"{self.base}/api/v1/analyses", files=files)
        if resp.status_code not in (200, 201):
            raise OcrError(f"OCR 上传失败 HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        analysis_id = data.get("analysis_id") or data.get("id")
        if not analysis_id:
            raise OcrError(f"OCR 响应缺少 analysis_id/id: {data}")
        return analysis_id

    async def confirm(self, analysis_id: str) -> None:
        client = await self._http()
        resp = await client.post(f"{self.base}/api/v1/analyses/{analysis_id}/confirm")
        if resp.status_code not in (200, 201):
            raise OcrError(f"OCR confirm 失败 HTTP {resp.status_code}: {resp.text[:300]}")

    async def get_tenhou6(self, analysis_id: str) -> dict[str, Any]:
        client = await self._http()
        resp = await client.get(f"{self.base}/api/v1/analyses/{analysis_id}/export/tenhou6")
        if resp.status_code != 200:
            raise OcrError(f"OCR tenhou6 导出失败 HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()
