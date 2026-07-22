# Third-Party Licenses

The public MortalSim application repository must ship a complete inventory
of redistributed dependencies before a release is published. At minimum,
the release review must cover:

- Python runtime and PyTorch/CUDA runtime
- FastAPI, Uvicorn, Pydantic and their transitive dependencies
- React, React DOM, Vite and TypeScript
- Rust crates used by `libriichi`
- NVIDIA CUDA runtime components, when included in the CUDA archive

This working tree contains the inventory placeholder only. The release job
must generate an SBOM and copy the license texts into this file or an
accompanying `licenses/` directory.
