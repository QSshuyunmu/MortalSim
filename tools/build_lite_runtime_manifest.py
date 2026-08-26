#!/usr/bin/env python3
"""Create the signed-by-hash identity manifest consumed by Formal Lite."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED_FILES = (
    "mortal_lite_runtime.dll",
    "aoti_cuda_shims.dll",
    "cudart64_12.dll",
    "model.dll",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_dir", type=Path)
    parser.add_argument("--graph-manifest", type=Path)
    parser.add_argument("--build-id")
    args = parser.parse_args()

    runtime_dir = args.runtime_dir.resolve()
    files: dict[str, str] = {}
    for name in REQUIRED_FILES:
        path = runtime_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"required Lite runtime artifact is missing: {path}")
        files[name] = sha256(path)
    artifact_sha256 = hashlib.sha256(
        "".join(f"{name}:{files[name]}\n" for name in sorted(files)).encode("ascii")
    ).hexdigest()

    graph: dict[str, object] = {}
    if args.graph_manifest:
        graph = json.loads(args.graph_manifest.read_text(encoding="utf-8-sig"))
    manifest = {
        "manifest_version": 1,
        "runtime_abi": "mortalsim-lite-abi-2",
        "engine_id": "aoti-cuda-sm89",
        "decision_contract": "stable_advantage_v2",
        "compute_capability": "8.9",
        "batch_size": 1000,
        "batch_capacity": 1024,
        "precision_profile": "amp-static-advantage",
        "build_id": args.build_id or f"v0.3.0rc1-{artifact_sha256[:12]}",
        "artifact_sha256": artifact_sha256,
        "files": files,
        "graph_build": graph,
    }
    output = runtime_dir / "runtime_manifest.json"
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(output)
    print(artifact_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
