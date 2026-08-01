"""Safe, torch-free reader for the standard Mortal ``.pth`` checkpoint.

The normal ``torch.load`` API is intentionally not used here.  A checkpoint is
an ordinary ZIP archive containing a restricted pickle and raw tensor storage;
this reader accepts only the small set of pickle globals emitted by
``torch.save(state_dict)`` and turns the tensors into immutable byte records.
It never imports or executes code from the checkpoint.
"""

from __future__ import annotations

import collections
import pickle
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LiteWeightError(ValueError):
    """Raised when a checkpoint is not a supported Mortal state dictionary."""


@dataclass(frozen=True)
class _StorageType:
    dtype: str


@dataclass(frozen=True)
class _StorageRef:
    dtype: str
    key: str
    size: int


@dataclass(frozen=True)
class TensorRecord:
    storage: _StorageRef
    storage_offset: int
    shape: tuple[int, ...]
    stride: tuple[int, ...]
    requires_grad: bool = False

    @property
    def dtype(self) -> str:
        return self.storage.dtype


_DTYPE_BY_STORAGE = {
    "FloatStorage": ("float32", 4),
    "HalfStorage": ("float16", 2),
    "DoubleStorage": ("float64", 8),
    "LongStorage": ("int64", 8),
    "IntStorage": ("int32", 4),
    "ShortStorage": ("int16", 2),
    "CharStorage": ("int8", 1),
    "ByteStorage": ("uint8", 1),
    "BoolStorage": ("bool", 1),
}


class _SafeUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):  # noqa: ANN001
        if module == "collections" and name == "OrderedDict":
            return collections.OrderedDict
        if module == "torch" and name in _DTYPE_BY_STORAGE:
            return _StorageType(_DTYPE_BY_STORAGE[name][0])
        if module == "torch._utils" and name == "_rebuild_tensor_v2":
            return _rebuild_tensor_v2
        if module == "torch._utils" and name == "_rebuild_tensor":
            return _rebuild_tensor_v2
        if module == "torch._utils" and name == "_rebuild_parameter":
            return _rebuild_parameter
        raise LiteWeightError(f"unsupported checkpoint pickle global: {module}.{name}")

    def persistent_load(self, pid: Any):  # noqa: ANN401
        if not isinstance(pid, tuple) or len(pid) != 5 or pid[0] != "storage":
            raise LiteWeightError("unsupported checkpoint persistent object")
        _, storage_type, key, location, size = pid
        if not isinstance(storage_type, _StorageType) or not (
            location == "cpu" or (isinstance(location, str) and location.startswith("cuda"))
        ):
            raise LiteWeightError("checkpoint storage must use CPU/CUDA and a built-in dtype")
        if not isinstance(key, str) or not isinstance(size, int) or size < 0:
            raise LiteWeightError("invalid checkpoint storage metadata")
        return _StorageRef(storage_type.dtype, key, size)


def _rebuild_tensor_v2(
    storage: _StorageRef,
    storage_offset: int,
    shape: tuple[int, ...],
    stride: tuple[int, ...],
    requires_grad: bool,
    _backward_hooks: Any,
    _metadata: Any = None,
) -> TensorRecord:
    if not isinstance(storage, _StorageRef):
        raise LiteWeightError("invalid tensor storage")
    return TensorRecord(
        storage,
        int(storage_offset),
        tuple(int(x) for x in shape),
        tuple(int(x) for x in stride),
        bool(requires_grad),
    )


def _rebuild_parameter(data: TensorRecord, requires_grad: bool, _backward_hooks: Any = None) -> TensorRecord:
    return TensorRecord(data.storage, data.storage_offset, data.shape, data.stride, bool(requires_grad))


def _read_checkpoint(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise LiteWeightError(f"not a valid Mortal checkpoint: {exc}") from exc
    with archive:
        names = archive.namelist()
        pickle_name = next((name for name in names if name.endswith("/data.pkl")), None)
        if pickle_name is None:
            raise LiteWeightError("checkpoint has no data.pkl")
        prefix = pickle_name[: -len("data.pkl")]
        raw = archive.read(pickle_name)
        try:
            value = _SafeUnpickler(__import__("io").BytesIO(raw)).load()
        except LiteWeightError:
            raise
        except Exception as exc:  # pickle errors are intentionally normalized
            raise LiteWeightError(f"checkpoint metadata is invalid: {exc}") from exc
        if not isinstance(value, dict):
            raise LiteWeightError("checkpoint root must be a dictionary")
        storage: dict[str, bytes] = {}
        for name in names:
            if name.startswith(prefix + "data/"):
                storage[name[len(prefix + "data/") :]] = archive.read(name)
        return value, storage


def _tensor_bytes(record: TensorRecord, storage: dict[str, bytes]) -> bytes:
    payload = storage.get(record.storage.key)
    if payload is None:
        raise LiteWeightError(f"checkpoint storage {record.storage.key} is missing")
    item_size = _DTYPE_BY_STORAGE[next(k for k, v in _DTYPE_BY_STORAGE.items() if v[0] == record.dtype)][1]
    count = 1
    for dim in record.shape:
        if dim < 0:
            raise LiteWeightError("negative tensor dimension")
        count *= dim
    if count == 0:
        return b""
    if not record.stride:
        indices = [0]
    else:
        # Mortal state tensors are contiguous.  Refuse exotic views rather
        # than silently changing a weight's layout.
        expected = 1
        for dim, stride in zip(reversed(record.shape), reversed(record.stride)):
            if stride != expected:
                raise LiteWeightError("non-contiguous checkpoint tensor is unsupported")
            expected *= dim
        indices = [record.storage_offset]
    start = (record.storage_offset * item_size)
    end = start + count * item_size
    if start < 0 or end > len(payload):
        raise LiteWeightError("checkpoint tensor points outside its storage")
    return payload[start:end]


def load_mortal_state(path: str | Path) -> tuple[dict[str, Any], dict[str, tuple[str, tuple[int, ...], bytes]]]:
    """Return ``(config, state)`` without importing PyTorch.

    State keys are normalized to the AOTI graph names (``brain_*`` and
    ``dqn_*``); each value is ``(dtype, shape, contiguous bytes)``.
    """
    root, storage = _read_checkpoint(Path(path))
    config = root.get("config")
    mortal = root.get("mortal")
    dqn = root.get("current_dqn")
    if not isinstance(config, dict) or not isinstance(mortal, dict) or not isinstance(dqn, dict):
        raise LiteWeightError("checkpoint must contain config, mortal and current_dqn")
    state: dict[str, tuple[str, tuple[int, ...], bytes]] = {}
    for group_name, group, prefix in (("mortal", mortal, "brain"), ("current_dqn", dqn, "dqn")):
        for key, value in group.items():
            if not isinstance(key, str) or not isinstance(value, TensorRecord):
                raise LiteWeightError(f"{group_name} contains a non-tensor entry")
            if key.endswith("num_batches_tracked"):
                continue
            normalized = (prefix + "." + key).replace(".", "_")
            state[normalized] = (value.dtype, value.shape, _tensor_bytes(value, storage))
    return config, state


def fp32_to_fp16(data: bytes) -> bytes:
    if len(data) % 4:
        raise LiteWeightError("float32 tensor has an invalid byte length")
    values = struct.unpack("<%df" % (len(data) // 4), data)
    return struct.pack("<%de" % len(values), *values)
