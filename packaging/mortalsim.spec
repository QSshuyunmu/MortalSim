# PyInstaller onedir build for the CUDA-only Windows distribution.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

ROOT = Path(SPEC).resolve().parents[1]
web_dist = ROOT / "apps" / "web" / "dist"
manifest = ROOT / "models" / "MODEL_MANIFEST.json"
mortal = ROOT / "mortal"
simulator = ROOT / "simulator"
release = ROOT / "target" / "release"

torch_binaries = collect_dynamic_libs("torch")
torch_hidden = ["torch", "torch.nn", "torch.cuda"]
excel_hidden = collect_submodules("openpyxl")
datas = []
if web_dist.exists():
    datas.append((str(web_dist), "apps/web/dist"))
# Checkpoints are never part of the portable application. Users import a
# compatible local file after startup; this keeps model distribution outside
# of the public project and release pipeline.
kyoku_parser = simulator / "kyoku_sim_win.py"
if kyoku_parser.exists():
    datas.append((str(kyoku_parser), "simulator"))
if manifest.exists():
    datas.append((str(manifest), "models"))
for source in mortal.glob("*.py"):
    datas.append((str(source), "mortal"))

binaries = list(torch_binaries)
for filename in ("libriichi.cp313-win_amd64.pyd", "libriichi.dll"):
    path = release / filename
    if path.exists():
        binaries.append((str(path), "target/release"))

hiddenimports = list(torch_hidden) + list(excel_hidden) + [
    "apps.api.main",
    "apps.api.services",
    "apps.desktop_launcher.main",
    "mortal_app.service",
    "mortal_app.model_registry",
    "mortal_app.gpu_monitor",
    "numpy",
    "scipy",
    "scipy.sparse",
    "tkinter",
]

# PyInstaller's third-party hooks eagerly follow optional Torch export, data,
# plotting and JIT stacks installed in the build interpreter. MortalSim only
# performs eager CUDA inference; collecting those packages adds more than 1 GB
# of unrelated files to the portable build.
excluded_optional_stacks = [
    "torchvision",
    "torchaudio",
    "onnx",
    "onnxscript",
    "onnxruntime",
    "pandas",
    "pyarrow",
    "matplotlib",
    "numba",
    "llvmlite",
    "sklearn",
    "tensorboard",
    "tensorrt",
    "tensorflow",
    "pytest",
    "_pytest",
    "py",
    "pluggy",
    "PIL",
    "lxml",
]

a = Analysis(
    [str(ROOT / "run_mortalsim.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excluded_optional_stacks,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    name="MortalSim",
    exclude_binaries=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MortalSim",
)
