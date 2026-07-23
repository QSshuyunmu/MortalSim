# Third-Party Licenses

This file records the principal redistributed components. The release archive
also includes `SBOM.cdx.json`, generated from the packaged Python runtime,
`package-lock.json`, and `Cargo.lock`, as the versioned transitive inventory.
Copyright and license notices supplied inside dependency distributions remain
the property of their respective authors.

## Riichi Mahjong Tiles (Regular)

- Project: FluffyStuff/riichi-mahjong-tiles
- Source: https://github.com/FluffyStuff/riichi-mahjong-tiles
- License: CC0 1.0 Universal / public domain dedication
- Usage: the 34 standard Japanese mahjong tile faces and three red-five
  variants are distributed as lossless WebP files under
  `apps/web/public/tiles/`.
- License copy: `apps/web/public/tiles/LICENSE-FluffyStuff.md`

## Python and application runtime

- Python: PSF License Version 2
- PyTorch: BSD-3-Clause
- FastAPI: MIT
- Uvicorn: BSD-3-Clause
- Pydantic: MIT
- OpenPyXL: MIT
- PyInstaller: GPL-2.0-or-later with the PyInstaller bootloader exception

Pinned versions are declared in `requirements-app.txt`,
`requirements-cuda.txt`, and `pyproject.toml`.

## Web application

- React and React DOM: MIT
- Apache ECharts: Apache-2.0
- Lucide React: ISC
- Vite: MIT
- TypeScript: Apache-2.0

Exact versions and transitive JavaScript packages are locked in
`apps/web/package-lock.json`.

## Rust core

The Rust dependency graph is locked in `Cargo.lock`. Its license expressions
are predominantly `MIT OR Apache-2.0`, with additional permissive
BSD-2-Clause, ISC, Zlib, BSL-1.0, Unicode-3.0, CC0-1.0, Unlicense, and
LLVM-exception combinations. The generated release SBOM lists every crate and
version. `libriichi` and MortalSim-owned Rust code remain
AGPL-3.0-or-later.

## NVIDIA CUDA runtime

The CUDA release contains redistributable runtime libraries supplied through
the official CUDA-enabled PyTorch wheel. Those binaries are governed by the
NVIDIA CUDA Toolkit End User License Agreement and NVIDIA third-party notices,
not by MortalSim's AGPL license. Users must review NVIDIA's terms before using
the CUDA package.
