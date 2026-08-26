# Model Distribution Policy

MortalSim does not distribute, host, download, mirror, or bundle model
checkpoints. This applies to the source repository, GitHub Release assets,
and the application itself.

Users provide a local `.pth` file through **Settings and Diagnostics**. The
application stores an immutable local copy under the user's data directory,
validates its architecture and CUDA inference compatibility, and records its
SHA-256 in the run result. The checkpoint never leaves the user's machine.

Model files have their own terms and are outside this repository's
AGPL-3.0-or-later code licence. A checkpoint must not be added to a release
without a separately reviewed distribution policy and a deliberate project
policy change.
