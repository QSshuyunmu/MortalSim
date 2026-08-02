"""Prepare one validated Mortal Lite model for a private portable bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mortal_app.model_registry import ModelRegistry


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_chunks(path: Path):
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            yield chunk


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    model_path = args.model.resolve()
    archive_path = args.archive.resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"model not found: {model_path}")
    if not archive_path.is_file():
        raise FileNotFoundError(f"portable archive not found: {archive_path}")

    for name in ("runs", "logs", "telemetry", "cache"):
        (data_dir / name).mkdir(parents=True, exist_ok=True)

    registry = ModelRegistry(data_dir)
    entry = registry.import_chunks(model_path.name, file_chunks(model_path), engine="lite")
    stored_path = registry.root / str(entry["stored_filename"])
    expected_hash = sha256(model_path)
    if sha256(stored_path) != expected_hash:
        raise RuntimeError("stored model hash differs from the input model")

    manifest = {
        "schema_version": 1,
        "bundle_type": "private-local-lite",
        "generated_at": datetime.now(UTC).isoformat(),
        "portable_archive": {
            "filename": archive_path.name,
            "sha256": sha256(archive_path),
        },
        "model": {
            "id": entry["id"],
            "label": entry["label"],
            "sha256": expected_hash,
            "size_bytes": entry["size_bytes"],
            "version": entry["version"],
            "conv_channels": entry["conv_channels"],
            "num_blocks": entry["num_blocks"],
            "decision_contract": "stable_advantage_v2",
        },
        "privacy": {
            "data_directory": "data",
            "contains_model": True,
            "publishable": False,
        },
    }
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
