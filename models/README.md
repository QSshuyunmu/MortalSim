# Local Model Library

No model checkpoint is stored in this repository or shipped in MortalSim
Release assets. MortalSim does not publish checkpoint sources, links, or
downloaders.

After starting the application, import a compatible local `.pth` file from
**Settings and Diagnostics**. The application validates the file without
executing checkpoint-provided code, then stores an immutable copy in the
user's local application-data directory. Its SHA-256 is recorded with each
simulation for reproducibility.

Do not add `.pth` or `.onnx` files to source control or release archives.
