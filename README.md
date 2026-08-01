# MortalSim

[简体中文安装与使用指南](README.zh-CN.md)

<p align="center">
  <img src="apps/web/public/mascot.webp" alt="MortalSim red crab mascot holding a mahjong tile" width="160">
</p>

MortalSim is a local Windows web desktop application for comparing Mortal
first-discard simulations. The Lite release runs the Rust `libriichi` runner
and a libtorch-free CUDA graph locally; hand data, seeds, telemetry and
results are not uploaded.

It is an offline analysis tool. It does not connect to a mahjong game client,
intercept network traffic, or automate live play. The current user interface
is Simplified Chinese.

## 中文说明

MortalSim 是一个只在本机运行的日麻自亲第一打对比工具。下载 Lite ZIP
后解压，双击 `Start-MortalSim.cmd`，浏览器会自动打开本地页面；不需要另外
安装 Python、Rust 或 CUDA Toolkit，但必须有可用的 NVIDIA 驱动和显卡。
首次进入“设置与诊断”导入自己的 Mortal v4 `.pth` 权重，再到“新建分析”
输入 14 张牌（最后一张固定作为第一摸）、宝牌指示和候选第一打即可开始。
运行记录、模型副本、GPU 采样和导出文件都保存在
`%LOCALAPPDATA%\MortalSim`，不会上传到服务器。

详细步骤、常见错误、模型导入和卸载方式见
[`docs/INSTALL.md`](docs/INSTALL.md)、[`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)
和 [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)。结果页支持全量
指标表的 JSON、Excel 和离线 HTML 导出。

![MortalSim 红蟹吉祥物](apps/web/public/mascot.webp)

> Lite 原生 CUDA 图目前仍需通过固定 seed 的逐局严格一致性验收；在该门槛
> 通过前，请把 [`docs/LITE_VALIDATION.md`](docs/LITE_VALIDATION.md) 中的
> PyTorch AMP Reference 作为权威对照，不要把近似结果当作已证明完全相同。

## Features

- Fixed-seed comparison of multiple first-discard candidates
- NAGA-compatible average round-balance statistics with confidence intervals
- Five mutually exclusive terminal outcomes and detailed win, defense,
  riichi, tenpai, call, and yaku metrics
- Background history extension, cancellation, replay, and GPU telemetry
- Local model library with SHA-256 identity and CUDA compatibility checks
- Excel, JSON, and self-contained HTML exports

## Quick Start

Download `MortalSim-Windows-x64-Lite-*.zip` from a GitHub Release. Extract it
to a normal folder and double-click `Start-MortalSim.cmd`. MortalSim is
GPU-only: an NVIDIA GPU and a current driver are required. Python, Rust and
CUDA Toolkit are not required at runtime. The app listens on `127.0.0.1` and
opens the browser automatically.

MortalSim never ships or downloads a model checkpoint. After the app opens,
import a local compatible Mortal v4 `.pth` file from **Settings and
Diagnostics**. The model remains in the local application data directory;
MortalSim does not upload it. See `MODEL_LICENSE.md`.

For development:

```powershell
python -m pip install -r requirements-lock.txt
python -m pip install -r requirements-test.txt
npm --prefix apps/web ci
npm --prefix apps/web run build
python run_mortalsim.py
```

Model weights are intentionally not committed. For local development, a
compatible v4 checkpoint may be placed at
`models/model_v4_20240308_best_min.pth`; public builds still exclude it.

Run the source checks with:

```powershell
python -m pytest tests mortal_app/test_gpu_monitor.py -q
cargo test -p libriichi --lib
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

## Status

`v0.2.0-alpha.0` is a prerelease. The Lite package is the compact GPU
distribution; its native graph is still subject to the fixed-seed strict
equivalence gate. Set `MORTALSIM_ENGINE=python` in a development environment
to use the PyTorch AMP reference path for authoritative comparisons.
See `docs/INSTALL.md`,
`docs/USER_GUIDE.md` and `docs/SMOKE_TEST.md`.

## License

Application code is AGPL-3.0-or-later. Dependencies, model weights and CUDA
runtime components may have separate terms; see `NOTICE`,
`THIRD_PARTY_LICENSES.md` and `MODEL_LICENSE.md`.
