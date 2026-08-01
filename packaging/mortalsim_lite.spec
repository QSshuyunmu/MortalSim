"""PyInstaller onedir spec for the libtorch-free MortalSim Lite build."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPEC).resolve().parents[1]
web_dist = ROOT / "apps" / "web" / "dist"
manifest = ROOT / "models" / "MODEL_MANIFEST.json"
release = ROOT / "target" / "release"

datas = []
if web_dist.exists():
    datas.append((str(web_dist), "apps/web/dist"))
parser = ROOT / "simulator" / "kyoku_sim_win.py"
if parser.exists():
    datas.append((str(parser), "simulator"))
if manifest.exists():
    datas.append((str(manifest), "models"))
for source in (ROOT / "mortal").glob("*.py"):
    datas.append((str(source), "mortal"))

binaries = []
for filename in ("libriichi.cp313-win_amd64.pyd", "libriichi.dll"):
    path = release / filename
    if path.exists():
        binaries.append((str(path), "target/release"))

hiddenimports = list(collect_submodules("openpyxl")) + [
    "apps.api.main",
    "apps.api.services",
    "apps.desktop_launcher.main",
    "mortal_app.service",
    "mortal_app.model_registry",
    "mortal_app.gpu_monitor",
    "mortal.lite_engine",
    "mortal.lite_weights",
    "numpy",
]

# The Lite build has no torch dependency.  Keeping this exclusion list here
# also prevents a developer's installed PyTorch from being pulled in by an
# accidental optional import during analysis.
excluded = [
    "torch", "torch.*", "torchvision", "torchaudio", "onnx", "onnxruntime",
    "pandas", "pyarrow", "scipy", "matplotlib", "numba", "llvmlite", "sklearn",
    "tensorboard", "tensorrt", "tensorflow", "pytest", "_pytest", "py", "pluggy",
    "PIL", "lxml", "tkinter", "_tkinter",
]

a = Analysis(
    [str(ROOT / "run_mortalsim.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excluded,
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
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MortalSim")
