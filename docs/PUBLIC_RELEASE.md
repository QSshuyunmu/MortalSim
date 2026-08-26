# Public Release Gate

The public candidate is the checkpoint-free `Lite` archive. It contains the
application, Rust extension, web assets and the libtorch-free CUDA runtime in
one portable ZIP. Users extract it and run `Start-MortalSim.cmd`.

## Mandatory gates

1. Confirm no checkpoint file, checkpoint download link, or checkpoint source
   is included in the public repository or release notes.
2. Run `python -m pytest tests mortal_app/test_gpu_monitor.py -q`,
   `cargo test -p libriichi --lib`, and the web typecheck/build.
3. Build the Lite package with `packaging/build_lite_windows.ps1` and verify
   its filename and SHA-256 with `packaging/verify_release.ps1`.
4. On a clean Windows x64 machine with an NVIDIA GPU, extract the Lite ZIP,
   start through `Start-MortalSim.cmd`, import a compatible local model, and
   run the fixed-seed GPU smoke test.
5. Generate and attach an SBOM, the Lite archive, `SHA256SUMS-Lite.txt`, and
   the release notes to the tagged GitHub Release.
6. Create the public repository through
   `packaging/prepare_public_repo.ps1 -Destination <empty-directory>` rather
   than pushing this working directory's historical Git metadata.

## Checkpoint-free public package

The public package is checkpoint-free by policy. It allows the user to import
a compatible local `.pth` through Settings, but must not contain, download,
name a source for, or market a checkpoint.
