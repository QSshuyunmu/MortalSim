#!/usr/bin/env python3
"""Capture numerical checkpoints for one immutable decision batch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "mortal"), str(ROOT / "target" / "release")]

from model import Brain, DQN, ResBlock  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=1)
    parser.add_argument("--mode", choices=("autocast", "fp32"), default="autocast")
    args = parser.parse_args()

    state = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    config = state["config"]
    version = int(config["control"]["version"])
    brain = Brain(
        version=version,
        conv_channels=int(config["resnet"]["conv_channels"]),
        num_blocks=int(config["resnet"]["num_blocks"]),
    ).eval().cuda()
    dqn = DQN(version=version).eval().cuda()
    brain.load_state_dict(state["mortal"], strict=True)
    dqn.load_state_dict(state["current_dqn"], strict=True)

    source = np.load(args.batch)
    obs = torch.from_numpy(source["obs"][: args.rows]).cuda()
    mask = torch.from_numpy(source["mask"][: args.rows]).cuda()
    captures: dict[str, np.ndarray] = {"mask": mask.cpu().numpy()}
    hooks = []

    def capture(name: str):
        def hook(_module, _inputs, output):
            captures[name] = output.detach().float().cpu().numpy()

        return hook

    residual_index = 0
    for module in brain.encoder.net:
        if isinstance(module, ResBlock):
            residual_index += 1
            if residual_index % 6 == 0:
                hooks.append(module.register_forward_hook(capture(f"residual_{residual_index - 6:02d}_{residual_index - 1:02d}")))
                hooks.append(module.ca.register_forward_hook(capture(f"channel_attention_{residual_index - 1:02d}")))
    hooks.append(brain.encoder.net[0].register_forward_hook(capture("stem")))

    enabled = args.mode == "autocast"
    with torch.inference_mode(), torch.autocast("cuda", enabled=enabled):
        phi = brain(obs)
        value, advantage = dqn.net(phi).split((1, 46), dim=-1)
        q = dqn(phi, mask)
    captures.update(
        phi=phi.detach().float().cpu().numpy(),
        value=value.detach().float().cpu().numpy(),
        advantage=advantage.detach().float().cpu().numpy(),
        q=q.detach().float().cpu().numpy(),
    )
    for hook in hooks:
        hook.remove()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, **captures)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
