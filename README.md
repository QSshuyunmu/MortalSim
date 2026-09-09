# MortalSim

[简体中文详细指南](README.zh-CN.md) | **English**

<p align="center">
  <img src="apps/web/public/mascot.webp" alt="MortalSim red crab mascot" width="160">
</p>

<p align="center">
  <strong>Next-Generation Riichi Mahjong Monte Carlo Decision Simulation & Analysis System</strong><br>
  Local PyTorch CUDA / High-Performance Rust <code>libriichi</code> / Multi-Rule Expected Value Modeling (Tenhou & M-League) / QQ Bot Integration
</p>

---

## What is MortalSim?

**MortalSim** is a high-performance, local Riichi Mahjong decision 推演 (simulation & analysis) engine. It leverages the state-of-the-art **Mortal AI** neural network alongside a high-throughput physical game simulator written in Rust (`libriichi`).

Unlike static supervised policy evaluators that only report single-step probabilities, MortalSim conducts **large-scale forward Monte Carlo rollouts** (hundreds to thousands of games in parallel) starting from an arbitrary mid-game or opening board state. It directly samples complete game outcomes under physical wall constraints and computes true expected values across distinct tournament rulesets.

### Key Capabilities

1. **Arbitrary Turn & Context Snapshots ($x \ge 1$, all 4 seats)**:
   - Full support for East, South, West, and North players across arbitrary rounds ($E1-0$ to $S4-x$).
   - Multi-turn chronological river modeling with causal temporal clamping.
   - Comprehensive action decision support: Discard, Riichi, Concealed Kan, Melds (Chi / Pon / Daiminkan), Kyuushu Kyuuhai, Win (Tsumo / Ron), and Pass (见逃).

2. **Dual-Rule Parallel Expected Value Optimization**:
   - **Tenhou Houou 7-Dan PT (凤七 pt EV)**: Specialized 4th-avoidance (避四) rating system modeling.
   - **Official M-League PTEV**: Official point spread with $+50 / +10 / -10 / -30$ Uma placement bonuses, tailored for aggressive top-spot contention (争一).
   - Side-by-side comparative decision verdict: automatically distinguishes *Consensus Optimal (全规则一致最优)* from *Tenhou vs M-League rule trade-offs*.

3. **Statistical Rigor & Convergence Acceleration**:
   - **ROPE State Machine ($\epsilon = 0.5\text{ pt}$)**: Paired Student's $t$-test across Common Random Numbers (CRN), dynamically providing confidence badges:
     - 🌟 **明确优选 (Clear Best)**
     - ⚖️ **伯仲均可 (Practically Equivalent)**
     - ⚠️ **尚不明确 (Inconclusive / Sample Insufficient)**
   - **Chan's Parallel Variance Reduction & Historical Store**: Canonical state fingerprinting (BLAKE3 / SHA-256) seamlessly pools past simulation runs, accelerating confidence intervals without redundant GPU waste.
   - **Strict Physical Invariants**: Non-overlapping random seed management, no-duplicate-tile live wall guarantees (70 tiles), and natural discard distribution without repetitive hand-discard artifacts.

4. **Zero-Configuration Neural AI Top-3 Discard Recommendation**:
   - Omitting candidate actions automatically triggers instantaneous neural network forward inference to select the top-3 highest Q-value candidate discards for rollout.

5. **Integrated QQ Bot & Automated Supervisor (OneBot 11 / NapCat)**:
   - Complete asynchronous bot bridge with 4K dark-themed decision card rendering.
   - Win32 Mutex process singletons, crash self-healing daemon, and lock-free async queue management.

---

## Architecture Overview

```
                        ┌──────────────────────────────┐
                        │   QQ Bot / OneBot 11 WS/HTTP │
                        │ (Natural Language /sim Cmds) │
                        └──────────────┬───────────────┘
                                       │
                                       ▼
┌───────────────────────┐      ┌──────────────────────────────┐
│  Web Workbench (Vite) │◄────►│  FastAPI Backend (Port 50715)│
└───────────────────────┘      └──────────────┬───────────────┘
                                              │
             ┌────────────────────────────────┴────────────────────────────────┐
             ▼                                                                 ▼
┌───────────────────────────┐                                     ┌───────────────────────────┐
│   Python PyTorch CUDA     │                                     │   Rust Core (libriichi)   │
│  • Mortal v4 / Distill 41b│◄───────────────────────────────────►│  • CustomKyokuRunner      │
│  • Instantaneous Q-eval   │        Batch Tensor & Masks         │  • Forward Native Rollout │
│  • Mixed-precision AMP    │                                     │  • MCMC Subfamily Sampler │
└───────────────────────────┘                                     └───────────────────────────┘
             │                                                                 │
             └────────────────────────────────┬────────────────────────────────┘
                                              ▼
                               ┌──────────────────────────────┐
                               │     MortalSim Engine Core    │
                               │  • Dual-rule PTEV Evaluator  │
                               │  • Chan Parallel Reducer     │
                               │  • ROPE Confidence Engine    │
                               └──────────────────────────────┘
```

---

## Quick Start

### 1. Prerequisites
- Windows 10/11 x64
- NVIDIA GPU with CUDA support (Recommended RTX 30/40 series, SM 8.0+)
- Python 3.11 - 3.13

### 2. Running MortalSim Local Engine
```powershell
# Clone the repository
git clone https://github.com/QSshuyunmu/MortalSim.git
cd MortalSim

# Install Python dependencies
python -m pip install -r requirements-lock.txt

# Start backend server (listening on 127.0.0.1:50715)
python run_mortalsim.py
```

### 3. Deploying the QQ Bot Bridge (Optional)
The integrated QQ Bot bridge is located under `bot/`:
```powershell
cd bot
# Start daemon supervisor (guards singleton and auto-restarts on failure)
python src/daemon.py
```

---

## Command Syntax Guide (QQ Bot & API)

Basic Format:
```text
/sim 手牌 d宝牌 [c候选] [局-本场] [座次] [巡目] [点数] [局数]
```

### Examples:
- **Minimal Discard (AI picks Top-3 Discards)**:
  ```text
  /sim 123456789m789s12p d8p
  ```
- **Custom Candidate Discards & Riichi**:
  ```text
  /sim 123456789m789s12p d8p c1pr,2p E1-0 1000
  ```
- **Mid-game Turn 7 with Score Differences**:
  ```text
  /sim 34567889m233789p d1m S4-0 seat=南 x=7 P180,200,390,230 1000
  ```
- **Reaction (Call / Pass / Ron)**:
  ```text
  /sim 77m4p4056799s112z d5s c=pon>4p,pass seat=东 x=2
  ```

---

## License

Application source code is licensed under **AGPL-3.0-or-later**. See `LICENSE` and `NOTICE` for details.
Mortal model weights, tile assets, and third-party dependencies retain their respective licenses.
