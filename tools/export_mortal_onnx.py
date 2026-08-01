#!/usr/bin/env python3
"""Export a user-supplied Mortal checkpoint for Lite runtime experiments."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from torch import nn


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mortal"))
for extension_dir in (
    ROOT / "target" / "release",
    ROOT / "dist" / "MortalSim" / "_internal" / "target" / "release",
):
    if extension_dir.is_dir():
        sys.path.insert(0, str(extension_dir))
        break

from model import Brain, DQN  # noqa: E402


class MortalPolicy(nn.Module):
    def __init__(self, brain: Brain, dqn: DQN) -> None:
        super().__init__()
        self.brain = brain
        self.dqn = dqn

    def forward(self, obs: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        return self.dqn(self.brain(obs), mask)


def build_policy(checkpoint: Path) -> MortalPolicy:
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    config = state["config"]
    version = int(config["control"]["version"])
    if version != 4:
        raise ValueError(f"Lite prototype currently supports Mortal v4, got v{version}")

    brain = Brain(
        version=version,
        conv_channels=int(config["resnet"]["conv_channels"]),
        num_blocks=int(config["resnet"]["num_blocks"]),
    ).eval()
    dqn = DQN(version=version).eval()
    brain.load_state_dict(state["mortal"], strict=True)
    dqn.load_state_dict(state["current_dqn"], strict=True)
    return MortalPolicy(brain, dqn).eval()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--precision", choices=("fp32", "amp"), default="fp32")
    parser.add_argument("--fixed-batch", type=int)
    parser.add_argument("--verify-batches", type=int, nargs="+", default=[1, 8, 64])
    args = parser.parse_args()

    policy = build_policy(args.checkpoint)
    device = torch.device("cuda" if args.precision == "amp" else "cpu")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("AMP export requires an available CUDA device")
    policy = policy.to(device)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    export_batch = args.fixed_batch or 2
    obs = torch.zeros((export_batch, 1012, 34), dtype=torch.float32, device=device)
    mask = torch.ones((export_batch, 46), dtype=torch.bool, device=device)
    dynamic_axes = None
    if args.fixed_batch is None:
        dynamic_axes = {
            "obs": {0: "batch"},
            "mask": {0: "batch"},
            "q_values": {0: "batch"},
        }
    with torch.autocast(device.type, enabled=args.precision == "amp"):
        torch.onnx.export(
            policy,
            (obs, mask),
            args.output,
            input_names=["obs", "mask"],
            output_names=["q_values"],
            opset_version=18,
            dynamo=False,
            dynamic_axes=dynamic_axes,
            do_constant_folding=True,
        )

    model = onnx.load(args.output)
    onnx.checker.check_model(model)
    session = ort.InferenceSession(str(args.output), providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(42)
    worst = 0.0
    verify_batches = [args.fixed_batch] if args.fixed_batch else args.verify_batches
    for batch_size in verify_batches:
        obs_np = rng.random((batch_size, 1012, 34), dtype=np.float32)
        mask_np = rng.random((batch_size, 46)) > 0.2
        mask_np[:, 45] = True
        with torch.inference_mode(), torch.autocast(device.type, enabled=args.precision == "amp"):
            expected = policy(
                torch.from_numpy(obs_np).to(device),
                torch.from_numpy(mask_np).to(device),
            ).float().cpu().numpy()
        actual = session.run(["q_values"], {"obs": obs_np, "mask": mask_np})[0]
        finite = np.isfinite(expected) & np.isfinite(actual)
        worst = max(worst, float(np.max(np.abs(expected[finite] - actual[finite]))))
        if not np.array_equal(expected.argmax(-1), actual.argmax(-1)):
            raise RuntimeError(f"CPU ONNX argmax mismatch at batch {batch_size}")

    print(f"Exported {args.output} ({args.output.stat().st_size / 1024 / 1024:.1f} MiB)")
    print(f"ONNX checker PASS; CPU argmax PASS; max |dq|={worst:.6g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
