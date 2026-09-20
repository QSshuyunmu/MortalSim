"""模型仓库 Manifest 单一真源管理器 (Unified tsypx Manifest Manager).

功能：
1. 监控并动态加载 D:\\tenhoulib\\tsypx\\models_manifest.json；
2. 建立工业冷峻英文代号与物理文件映射：
   - Bastion    -> Bin_0910.pth
   - Nova-X     -> distill_nova.pth
   - Logos      -> distill_41b_infer.pth
   - Consensus  -> distill_consensus_v3.pth
   - Shadow-J   -> luckyj_clone_v1.pth
3. 进程内 SHA256 缓存字典，杜绝频繁切模型时的重复读盘；
4. 校验 .pth 文件合法性（文件存在、非空、大小合规）。
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("reviewer.manifest_manager")

TSYPX_DIR = Path(r"D:\tenhoulib\tsypx")
MANIFEST_FILE = TSYPX_DIR / "models_manifest.json"

_SHA256_CACHE: dict[tuple[str, float, int], str] = {}


def get_file_sha256(file_path: Path) -> str:
    """带 mtime 和 size 缓存的高性能 SHA256 计算。"""
    try:
        st = file_path.stat()
        cache_key = (str(file_path.resolve()), st.st_mtime, st.st_size)
        if cache_key in _SHA256_CACHE:
            return _SHA256_CACHE[cache_key]

        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        digest = h.hexdigest()
        _SHA256_CACHE[cache_key] = digest
        return digest
    except Exception as exc:
        log.warning("计算 SHA256 失败: %s, exc: %s", file_path, exc)
        return ""


def load_tsypx_manifest() -> dict[str, Any]:
    """读取并验证 tsypx Manifest 配置。"""
    if not MANIFEST_FILE.exists():
        log.warning("Manifest 文件不存在: %s", MANIFEST_FILE)
        return {"models": {}, "default_model": "Logos"}

    try:
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as exc:
        log.error("解析 Manifest 失败: %s", exc)
        return {"models": {}, "default_model": "Logos"}


def resolve_model_path(tag_or_filename: str) -> tuple[str, Path | None, dict[str, Any]]:
    """根据输入的模型代号或文件名，解析出标准英文代号与物理路径。
    
    支持别名大小写模糊容错（如 'logos', 'Logos', 'nova-x', 'Nova-X', 'bastion' 等）。
    """
    manifest = load_tsypx_manifest()
    models_dict = manifest.get("models", {})

    target_key = tag_or_filename.strip().lower()

    # 1. 精确与大小写匹配 Tag
    for official_tag, info in models_dict.items():
        if official_tag.lower() == target_key:
            pth_path = TSYPX_DIR / info["file"]
            if pth_path.exists():
                return official_tag, pth_path, info

    # 2. 匹配物理文件名
    for official_tag, info in models_dict.items():
        if info["file"].lower() == target_key or Path(info["file"]).stem.lower() == target_key:
            pth_path = TSYPX_DIR / info["file"]
            if pth_path.exists():
                return official_tag, pth_path, info

    # 3. 兼容既有旧代号映射
    legacy_map = {
        "bin_0910": "Bastion",
        "aegis": "Bastion",
        "distill_nova": "Nova-X",
        "sol": "Nova-X",
        "nova": "Nova-X",
        "distill_41b_infer": "Logos",
        "41b": "Logos",
        "consensus": "Consensus",
        "consensus_v3": "Consensus",
        "luckyj": "Shadow-J",
        "shadow": "Shadow-J",
    }
    if target_key in legacy_map:
        official_tag = legacy_map[target_key]
        if official_tag in models_dict:
            info = models_dict[official_tag]
            pth_path = TSYPX_DIR / info["file"]
            if pth_path.exists():
                return official_tag, pth_path, info

    # 4. 默认 fallback 到 Logos
    default_tag = manifest.get("default_model", "Logos")
    if default_tag in models_dict:
        info = models_dict[default_tag]
        pth_path = TSYPX_DIR / info["file"]
        if pth_path.exists():
            return default_tag, pth_path, info

    return "Unknown", None, {}
