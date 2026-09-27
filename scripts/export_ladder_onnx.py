# -*- coding: utf-8 -*-
"""为天梯补导出 3 款模型（xiaolin=DQN 常规导出；awr_luckyj/chouxiang=PolicyNet 头融合导出）。

输出图签名与 export_onnx.py 完全一致：(obs, mask) -> q_values，
PolicyNet 头（fc1->Mish->fc2）替代 DQN 头，语义与 MortalEngine 的 python 路径一致。
导出后用 onnxruntime 做逐动作一致性校验（与 export_onnx.verify 同款）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path("D:/tenhoulib")
sys.path.insert(0, str(ROOT / ".diag"))
sys.path.insert(0, str(ROOT / "Mortal"))
sys.path.insert(0, str(ROOT / "Mortal" / "mortal"))
sys.path.insert(0, str(ROOT / "colab_deploy"))

from model import Brain  # noqa: E402
from ladder_engine import PolicyNetHead  # noqa: E402

OUT = ROOT / "tsypx_onnx"
OBS_SHAPE = (1012, 34)
ACTION_SPACE = 46
TSYPX = ROOT / "tsypx"


def load_brain(st):
    cfg = st.get("config") or {}   # awr_luckyj/chouxiang 无 config 键，默认 v4/192/40（已验证）
    ver = cfg.get("control", {}).get("version", 4)
    b = Brain(version=ver, conv_channels=cfg.get("resnet", {}).get("conv_channels", 192),
              num_blocks=cfg.get("resnet", {}).get("num_blocks", 40)).eval()
    b.load_state_dict(st.get("mortal") or st.get("brain"))
    return b, ver


def export_fused(name: str, st, head_state: dict, head_of_brain):
    b, ver = load_brain(st)
    head = head_of_brain(head_state).eval()
    full = torch.nn.Sequential(b, head) if False else None

    class Full(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.brain, self.head = b, head

        def forward(self, obs, mask):
            return self.head(self.brain(obs), mask)

    full = Full().eval()
    dst = OUT / (name + ".onnx")
    torch.onnx.export(
        full,
        (torch.zeros((1,) + OBS_SHAPE), torch.ones((1, ACTION_SPACE), dtype=torch.bool)),
        str(dst),
        input_names=["obs", "mask"], output_names=["q_values"],
        dynamic_axes={"obs": {0: "batch"}, "mask": {0: "batch"}},
        opset_version=17, dynamo=False,
    )
    return full, dst, ver


def verify(full, dst: Path, n: int = 40):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    sess = ort.InferenceSession(str(dst), so, providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(12345)
    bad, maxdiff = 0, 0.0
    for i in range(n):
        bs = (1, 3, 4, 8)[i % 4]
        obs = rng.standard_normal((bs,) + OBS_SHAPE).astype(np.float32)
        mask = rng.random((bs, ACTION_SPACE)) > 0.25
        mask[:, 0] = True
        with torch.inference_mode():
            q_t = full(torch.as_tensor(obs), torch.as_tensor(mask)).numpy()
        q_o = sess.run(["q_values"], {"obs": obs, "mask": mask})[0]
        maxdiff = max(maxdiff, float(np.abs(q_t - q_o).max()))
        if not np.array_equal(q_t.argmax(-1), q_o.argmax(-1)):
            bad += 1
    return bad, maxdiff, n


def main():
    OUT.mkdir(exist_ok=True)

    # 1) xiaolin_clone_v1_infer：DQN 常规融合
    st = torch.load(str(TSYPX / "xiaolin_clone_v1_infer.pth"), map_location="cpu",
                    weights_only=False)
    cfg = st["config"]
    ver = cfg["control"]["version"]
    b = Brain(version=ver, conv_channels=cfg["resnet"]["conv_channels"],
              num_blocks=cfg["resnet"]["num_blocks"]).eval()
    b.load_state_dict(st["mortal"])
    d = torch.load(str(TSYPX / "xiaolin_clone_v1_infer.pth"), map_location="cpu",
                   weights_only=False)
    from model import DQN
    dqn = DQN(version=ver).eval()
    dqn.load_state_dict(st["current_dqn"])

    class FullDQN(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.brain, self.dqn = b, dqn

        def forward(self, obs, mask):
            return self.dqn(self.brain(obs), mask)

    t0 = time.time()
    full = FullDQN().eval()
    dst = OUT / "xiaolin_clone_v1_infer.onnx"
    torch.onnx.export(full,
                      (torch.zeros((1,) + OBS_SHAPE), torch.ones((1, ACTION_SPACE), dtype=torch.bool)),
                      str(dst), input_names=["obs", "mask"], output_names=["q_values"],
                      dynamic_axes={"obs": {0: "batch"}, "mask": {0: "batch"}},
                      opset_version=17, dynamo=False)
    bad, maxdiff, n = verify(full, dst)
    print(f"OK  xiaolin_clone_v1_infer  {dst.stat().st_size/2**20:.1f} MiB  导出{time.time()-t0:.0f}s  "
          f"动作不一致 {bad}/{n}  max|dq|={maxdiff:.2e}", flush=True)

    # 2) awr_luckyj / chouxiang：Brain + PolicyNet 头融合
    for name, key in (("awr_luckyj", "policy"), ("chouxiang", "policy_net")):
        st = torch.load(str(TSYPX / f"{name}.pth"), map_location="cpu", weights_only=False)
        t0 = time.time()
        full, dst, ver = export_fused(name, st, st[key], PolicyNetHead)
        bad, maxdiff, n = verify(full, dst)
        print(f"OK  {name:<24} {dst.stat().st_size/2**20:.1f} MiB  导出{time.time()-t0:.0f}s  "
              f"动作不一致 {bad}/{n}  max|dq|={maxdiff:.2e}", flush=True)


if __name__ == "__main__":
    main()
