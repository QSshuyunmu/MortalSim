"""Local, immutable registry for user-imported Mortal model weights."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "models"
MORTAL_DIR = ROOT / "mortal"
LIBRIICHI_DIR = ROOT / "target" / "release"
DEFAULT_MODEL_ID = "distill_41b_infer"
PATH_41B = MODELS_DIR / "distill_41b_infer.pth"
PATH_NOVA = MODELS_DIR / "distill_nova.pth"
MAX_MODEL_BYTES = 2 * 1024 * 1024 * 1024


def data_dir() -> Path:
    configured = os.environ.get("MORTALSIM_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) / "MortalSim") if local else (Path.home() / ".mortalsim")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ModelRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or data_dir()) / "models"
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "models.json"

    def _index(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_index(self, entries: dict[str, dict[str, Any]]) -> None:
        temporary = self.index_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.index_path)

    @staticmethod
    def _with_contracts(item: dict[str, Any]) -> dict[str, Any]:
        is_mortal_v4 = item.get("version") == 4
        contracts = ["stable_advantage_v2", "legacy_amp_v1"]
        return {
            **item,
            "supported_decision_contracts": contracts,
            "lite_compatible": True,
            "incompatibility_reason": None,
        }

    def builtins(self) -> list[dict[str, Any]]:
        p1 = PATH_41B.exists()
        p2 = PATH_NOVA.exists()
        models = []
        if p1:
            models.append(self._with_contracts({
                "id": "distill_41b_infer",
                "label": "均衡模型 (distill_41b_infer: 攻防均衡/重视避四与顺位)",
                "filename": PATH_41B.name,
                "path": str(PATH_41B),
                "sha256": sha256(PATH_41B),
                "size_bytes": PATH_41B.stat().st_size,
                "version": 4,
                "conv_channels": 192,
                "num_blocks": 40,
                "engine": "python-amp",
                "source": "tsypx-distill-41b",
                "ready": True,
                "error": None,
            }))
        if p2:
            models.append(self._with_contracts({
                "id": "distill_nova",
                "label": "激进模型 (distill_nova: 门清立直/高打点/争一)",
                "filename": PATH_NOVA.name,
                "path": str(PATH_NOVA),
                "sha256": sha256(PATH_NOVA),
                "size_bytes": PATH_NOVA.stat().st_size,
                "version": 4,
                "conv_channels": 192,
                "num_blocks": 40,
                "engine": "python-amp",
                "source": "tsypx-distill-nova",
                "ready": True,
                "error": None,
            }))
        return models

    def list(self) -> list[dict[str, Any]]:
        models = self.builtins()
        # Aliases
        for item in self._index().values():
            path = self.root / item.get("stored_filename", "")
            if path.exists():
                models.append(self._with_contracts({**item, "path": str(path), "ready": True, "error": None}))
        return models

    def get(self, model_id: str | None) -> dict[str, Any]:
        requested = model_id or DEFAULT_MODEL_ID
        for item in self.list():
            if item["id"] == requested:
                if not item["ready"]:
                    raise RuntimeError(f"模型不可用: {item.get('error') or requested}")
                path = Path(item["path"])
                actual = sha256(path)
                if item.get("sha256") and actual.lower() != str(item["sha256"]).lower():
                    raise RuntimeError("模型 SHA256 不匹配，请重新导入")
                return {**item, "sha256": actual}
        raise RuntimeError(f"未找到模型: {requested}")

    @staticmethod
    def _prepare_imports() -> None:
        for path in (MORTAL_DIR, LIBRIICHI_DIR):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))

    def validate(self, path: Path) -> dict[str, Any]:
        """Never execute weight-provided code; require Mortal v1-v4 state dictionaries."""
        import torch

        self._prepare_imports()
        from libriichi.consts import ACTION_SPACE, obs_shape
        from model import Brain, DQN

        state = torch.load(path, map_location="cpu", weights_only=True)
        if not isinstance(state, dict) or not isinstance(state.get("config"), dict):
            raise ValueError("不是包含 config 的 Mortal 权重")
        config = state["config"]
        try:
            version = int(config["control"]["version"])
            channels = int(config["resnet"]["conv_channels"])
            blocks = int(config["resnet"]["num_blocks"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Mortal config 缺少 control.version 或 resnet 参数") from exc
        if version not in {1, 2, 3, 4}:
            raise ValueError(f"不支持 Mortal version={version}；当前只支持 v1-v4")
        if not isinstance(state.get("mortal"), dict) or not isinstance(state.get("current_dqn"), dict):
            raise ValueError("权重缺少 mortal 或 current_dqn state_dict")
        brain = Brain(version=version, conv_channels=channels, num_blocks=blocks)
        dqn = DQN(version=version)
        brain.load_state_dict(state["mortal"], strict=True)
        dqn.load_state_dict(state["current_dqn"], strict=True)
        if not torch.cuda.is_available():
            raise RuntimeError("导入自检需要 CUDA，但 CUDA 当前不可用")
        device = torch.device("cuda")
        brain.eval().to(device)
        dqn.eval().to(device)
        try:
            with torch.inference_mode(), torch.autocast(device_type="cuda", enabled=True):
                obs = torch.zeros((1, *obs_shape(version)), device=device)
                mask = torch.ones((1, ACTION_SPACE), dtype=torch.bool, device=device)
                dqn(brain(obs), mask)
            torch.cuda.synchronize(device)
        finally:
            del brain, dqn
            torch.cuda.empty_cache()
        return {"version": version, "conv_channels": channels, "num_blocks": blocks}

    def validate_lite(self, path: Path) -> dict[str, Any]:
        """Validate the Lite-compatible checkpoint without importing PyTorch."""
        from mortal.lite_weights import LiteWeightError, load_mortal_state

        try:
            config, state = load_mortal_state(path)
            version = int(config["control"]["version"])
            channels = int(config["resnet"]["conv_channels"])
            blocks = int(config["resnet"]["num_blocks"])
        except (KeyError, TypeError, ValueError, LiteWeightError) as exc:
            raise ValueError(f"invalid Mortal Lite checkpoint: {exc}") from exc
        if (version, channels, blocks) != (4, 256, 54):
            raise ValueError("Mortal Lite supports only v4 with 256 channels and 54 blocks")
        if len(state) != 767:
            raise ValueError(f"Mortal Lite expects 767 tensors, found {len(state)}")
        return {"version": version, "conv_channels": channels, "num_blocks": blocks, "lite_compatible": True}

    def register_staged(
        self,
        temporary: Path,
        filename: str,
        model_hash: str,
        written: int,
        *,
        engine: str = "lite",
    ) -> dict[str, Any]:
        safe_name = Path(filename).name
        if not safe_name.lower().endswith(".pth"):
            raise ValueError("只接受 .pth 权重文件")
        model_id = f"mortal-{model_hash[:16]}"
        entries = self._index()
        existing = entries.get(model_id)
        if existing:
            return {**existing, "duplicate": True}
        architecture = self.validate_lite(temporary) if engine == "lite" else self.validate(temporary)
        stored_filename = f"{model_hash}.pth"
        temporary.replace(self.root / stored_filename)
        entry = {
            "id": model_id,
            "label": Path(safe_name).stem,
            "filename": safe_name,
            "stored_filename": stored_filename,
            "sha256": model_hash,
            "size_bytes": written,
            "engine": "mortal-lite" if engine == "lite" else "python-amp",
            "source": "imported",
            "ready": True,
            "error": None,
            **architecture,
        }
        entry = self._with_contracts(entry)
        entries[model_id] = entry
        self._write_index(entries)
        return entry

    def import_chunks(self, filename: str, chunks: Iterable[bytes], *, engine: str = "lite") -> dict[str, Any]:
        safe_name = Path(filename).name
        temporary = self.root / f".{os.getpid()}-{safe_name}.upload"
        written, digest = 0, hashlib.sha256()
        try:
            with temporary.open("xb") as destination:
                for chunk in chunks:
                    written += len(chunk)
                    if written > MAX_MODEL_BYTES:
                        raise ValueError("模型文件超过 2 GiB 限制")
                    digest.update(chunk)
                    destination.write(chunk)
            return self.register_staged(temporary, safe_name, digest.hexdigest(), written, engine=engine)
        finally:
            temporary.unlink(missing_ok=True)
