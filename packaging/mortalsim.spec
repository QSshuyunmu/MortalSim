# PyInstaller onedir build. Keep the CUDA package separate from the CPU package.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPEC).resolve().parents[1]
web_dist = ROOT / "apps" / "web" / "dist"
model = ROOT / "Akagi" / "model_v4_20240308_best_min.pth"
manifest = ROOT / "models" / "MODEL_MANIFEST.json"
mortal = ROOT / "mortal"
akagi = ROOT / "Akagi"
release = ROOT / "target" / "release"

torch_datas = collect_data_files("torch")
torch_binaries = collect_dynamic_libs("torch")
torch_hidden = ["torch", "torch.nn", "torch.cuda"]
datas = []
if web_dist.exists():
    datas.append((str(web_dist), "apps/web/dist"))
if model.exists():
    datas.append((str(model), "Akagi"))
kyoku_parser = ROOT / "Akagi" / "kyoku_sim_win.py"
if kyoku_parser.exists():
    datas.append((str(kyoku_parser), "Akagi"))
if manifest.exists():
    datas.append((str(manifest), "models"))
datas.append((str(mortal), "mortal"))
datas.extend(torch_datas)

binaries = list(torch_binaries)
for filename in ("libriichi.cp313-win_amd64.pyd", "libriichi.dll"):
    path = release / filename
    if path.exists():
        binaries.append((str(path), "target/release"))

hiddenimports = list(torch_hidden) + [
    "apps.api.main",
    "apps.api.services",
    "apps.desktop_launcher.main",
    "mortal_app.service",
    "mortal_app.gpu_monitor",
    "numpy",
    "tkinter",
]

a = Analysis(
    [str(ROOT / "run_mortalsim.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
