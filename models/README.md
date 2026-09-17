# Local Model Library

No model checkpoint is stored in this repository or shipped in MortalSim
Release assets. MortalSim does not publish checkpoint sources, links, or
downloaders.

After starting the application, import a compatible local `.pth` file from
**Settings and Diagnostics**. The application validates the file without
executing checkpoint-provided code, then stores an immutable copy in the
user's local application-data directory. Its SHA-256 is recorded with each
simulation for reproducibility.

Do not add model weights or generated runtime artifacts to source control.
Checkpoint formats (`.pth`, `.pt`, `.ckpt`, `.onnx`, `.safetensors`) and model
`.bin` / `.pkl` files are ignored, including nested model directories.

## Auxiliary rank models for local development

Development flows that use the LightGBM hanchan rank predictor expect these
local files under `models/hanchan_rank/`:

- `hanchan_rank_lgb_seat0.txt`
- `hanchan_rank_lgb_seat1.txt`
- `hanchan_rank_lgb_seat2.txt`
- `hanchan_rank_lgb_seat3.txt`

These are model weights, not source text. They are no longer tracked; a fresh
checkout does not supply them. Keep your existing local copies or provision
compatible files separately before using the rank predictor. The tracked
`hanchan_rank_model_manifest.json` is metadata, not a replacement for the models.
Removing files from the Git index preserves local copies and does not remove
older versions from Git history.
