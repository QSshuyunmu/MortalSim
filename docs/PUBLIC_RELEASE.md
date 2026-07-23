# Public Release Gate

MortalSim's CUDA distribution is intentionally split because GitHub Release
assets must be smaller than 2 GiB. A complete release contains one `Core`
archive and every `Runtime-XX` archive with the same version. Users extract
all of them into one directory and run `Start-MortalSim.cmd`.

## Mandatory gates

1. Confirm no checkpoint file, checkpoint download link, or checkpoint source
   is included in the public repository or release notes.
2. Run `python -m pytest tests mortal_app/test_gpu_monitor.py -q`,
   `cargo test -p libriichi --lib`, and the web typecheck/build.
3. Build the split package with `packaging/build_windows.ps1` and verify each
   filename and SHA-256 in `release/SHA256SUMS.txt`.
4. On a clean Windows x64 machine with an NVIDIA GPU, extract Core plus all
   Runtime archives, start through `Start-MortalSim.cmd`, import the intended
   model, and run the fixed-seed GPU smoke test.
5. Generate and attach an SBOM, all component archives, `SHA256SUMS.txt`, and
   the release notes to the tagged GitHub Release.
6. Create the public repository through
   `packaging/prepare_public_repo.ps1 -Destination <empty-directory>` rather
   than pushing this working directory's historical Git metadata.

## Checkpoint-free public package

The public package is checkpoint-free by policy. It allows the user to import
a compatible local `.pth` through Settings, but must not contain, download,
name a source for, or market a checkpoint.
