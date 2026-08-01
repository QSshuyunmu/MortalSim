"""Small ctypes adapter for the optional libtorch-free CUDA runtime.

The DLL owns the CUDA session and model weights. Python only supplies the
contiguous observation/mask buffers and receives ordinary lists matching the
existing MortalEngine contract.
"""

from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Any

import numpy as np

try:
    from .lite_weights import LiteWeightError, fp32_to_fp16, load_mortal_state
except ImportError:  # service.py also supports the legacy flat mortal/ import path
    from lite_weights import LiteWeightError, fp32_to_fp16, load_mortal_state


class _LiteTensorInput(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("data", ctypes.c_void_p),
        ("ndim", ctypes.c_int32),
        ("sizes", ctypes.c_int64 * 8),
        ("strides", ctypes.c_int64 * 8),
        ("dtype", ctypes.c_int32),
    ]


class MortalLiteEngine:
    engine_type = "mortal-lite"

    def __init__(
        self,
        runtime_path: str | Path,
        model_path: str | Path,
        weights_path: str | Path | None = None,
        *,
        checkpoint_path: str | Path | None = None,
        capacity: int = 1024,
        name: str = "Mortal Lite",
    ) -> None:
        self.name = name
        self.version = 4
        self.device = "cuda:0"
        self.capacity = int(capacity)
        self.runtime = ctypes.WinDLL(str(Path(runtime_path).resolve()))
        self.runtime.mortal_lite_create.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_int64,
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        self.runtime.mortal_lite_create.restype = ctypes.c_void_p
        self.runtime.mortal_lite_run.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_int64,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        self.runtime.mortal_lite_run.restype = ctypes.c_int
        self.runtime.mortal_lite_destroy.argtypes = [ctypes.c_void_p]
        self.runtime.mortal_lite_destroy.restype = None
        self.runtime.mortal_lite_constant_count.argtypes = [ctypes.c_void_p]
        self.runtime.mortal_lite_constant_count.restype = ctypes.c_int
        self.runtime.mortal_lite_constant_info.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_int),
        ]
        self.runtime.mortal_lite_constant_info.restype = ctypes.c_int
        self.runtime.mortal_lite_update_constants.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_LiteTensorInput),
            ctypes.c_size_t,
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        self.runtime.mortal_lite_update_constants.restype = ctypes.c_int
        runtime_dir = Path(runtime_path).resolve().parent
        shim_path = runtime_dir / "aoti_cuda_shims.dll"
        if not shim_path.exists():
            raise RuntimeError(f"Lite CUDA shim is missing: {shim_path}")
        error = ctypes.create_string_buffer(4096)
        self._handle = self.runtime.mortal_lite_create(
            str(Path(model_path).resolve()).encode(),
            str(Path(weights_path).resolve()).encode() if weights_path else None,
            str(shim_path).encode(),
            self.capacity,
            error,
            len(error),
        )
        if not self._handle:
            raise RuntimeError(error.value.decode("utf-8", "replace") or "Lite runtime initialization failed")
        if checkpoint_path is not None:
            try:
                self._load_checkpoint(Path(checkpoint_path))
            except Exception:
                self.close()
                raise

    def _load_checkpoint(self, path: Path) -> None:
        config, state = load_mortal_state(path)
        try:
            version = int(config["control"]["version"])
            channels = int(config["resnet"]["conv_channels"])
            blocks = int(config["resnet"]["num_blocks"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LiteWeightError("Mortal checkpoint has an invalid architecture") from exc
        if (version, channels, blocks) != (4, 256, 54):
            raise LiteWeightError(
                "Mortal Lite supports only v4 with 256 channels and 54 residual blocks"
            )
        count = self.runtime.mortal_lite_constant_count(self._handle)
        if count <= 0:
            raise RuntimeError("Lite model does not expose constant metadata")
        inputs: list[_LiteTensorInput] = []
        names: list[bytes] = []
        arrays: list[np.ndarray] = []
        size_arrays: list[Any] = []
        stride_arrays: list[Any] = []
        expected: set[str] = set()
        for index in range(count):
            name_buffer = ctypes.create_string_buffer(512)
            dtype = ctypes.c_int()
            if self.runtime.mortal_lite_constant_info(
                self._handle, index, name_buffer, len(name_buffer), ctypes.byref(dtype)
            ) != 0:
                raise RuntimeError(f"unable to inspect Lite constant {index}")
            name = name_buffer.value.decode("ascii")
            expected.add(name)
            value = state.get(name)
            if value is None:
                raise LiteWeightError(f"checkpoint is missing Lite constant {name}")
            source_dtype, shape, raw = value
            target_dtype = {5: "float16", 6: "float32"}.get(dtype.value)
            if target_dtype is None:
                raise RuntimeError(f"unsupported Lite constant dtype {dtype.value} for {name}")
            if source_dtype != target_dtype:
                if source_dtype == "float32" and target_dtype == "float16":
                    raw = fp32_to_fp16(raw)
                else:
                    raise LiteWeightError(f"dtype mismatch for {name}: {source_dtype} -> {target_dtype}")
            array = np.frombuffer(raw, dtype=np.float16 if target_dtype == "float16" else np.float32).copy()
            expected_elements = int(np.prod(shape, dtype=np.int64)) if shape else 1
            if array.size != expected_elements:
                raise LiteWeightError(f"shape/byte mismatch for {name}")
            array = array.reshape(shape or ())
            arrays.append(array)
            encoded_name = name.encode("ascii")
            names.append(encoded_name)
            ndim = len(shape)
            if ndim > 8:
                raise LiteWeightError(f"tensor rank is too large for {name}")
            sizes = (ctypes.c_int64 * 8)(*((*shape, *([1] * (8 - ndim))) if ndim else ([1] * 8)))
            contiguous = []
            stride = 1
            for dim in reversed(shape):
                contiguous.append(stride)
                stride *= dim
            contiguous.reverse()
            strides = (ctypes.c_int64 * 8)(*((*contiguous, *([1] * (8 - ndim))) if ndim else ([1] * 8)))
            size_arrays.append(sizes)
            stride_arrays.append(strides)
            inputs.append(
                _LiteTensorInput(
                    encoded_name,
                    array.ctypes.data,
                    ndim,
                    sizes,
                    strides,
                    dtype.value,
                )
            )
        if expected != set(state):
            extras = sorted(set(state) - expected)
            if extras:
                raise LiteWeightError(f"checkpoint contains unsupported Lite constants: {extras[:3]}")
        update_error = ctypes.create_string_buffer(4096)
        values = (_LiteTensorInput * len(inputs))(*inputs)
        if self.runtime.mortal_lite_update_constants(
            self._handle, values, len(inputs), update_error, len(update_error)
        ) != 0:
            raise RuntimeError(update_error.value.decode("utf-8", "replace") or "Lite weight import failed")

    def close(self) -> None:
        handle, self._handle = getattr(self, "_handle", None), None
        if handle:
            self.runtime.mortal_lite_destroy(handle)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def react_batch(self, obs: Any, masks: Any, invisible_obs: Any = None):
        del invisible_obs
        obs_array = np.ascontiguousarray(obs if isinstance(obs, np.ndarray) else np.stack(obs), dtype=np.float32)
        mask_array = np.ascontiguousarray(masks if isinstance(masks, np.ndarray) else np.stack(masks), dtype=np.bool_)
        if obs_array.ndim != 3 or obs_array.shape[1:] != (1012, 34):
            raise ValueError(f"Lite observation shape must be [batch,1012,34], got {obs_array.shape}")
        if mask_array.ndim != 2 or mask_array.shape[1] != 46 or mask_array.shape[0] != obs_array.shape[0]:
            raise ValueError(f"Lite mask shape must be [batch,46], got {mask_array.shape}")
        actions: list[int] = []
        q_values: list[list[float]] = []
        error = ctypes.create_string_buffer(4096)
        for start in range(0, obs_array.shape[0], self.capacity):
            stop = min(start + self.capacity, obs_array.shape[0])
            count = stop - start
            output = np.empty((count, 46), dtype=np.float32)
            result = self.runtime.mortal_lite_run(
                self._handle,
                obs_array[start:stop].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                mask_array[start:stop].ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
                count,
                output.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                error,
                len(error),
            )
            if result != 0:
                raise RuntimeError(error.value.decode("utf-8", "replace") or "Lite inference failed")
            valid = mask_array[start:stop]
            masked = np.where(valid, output, -np.inf)
            # Keep the same legal-action argmax semantics as the Python
            # reference.  The Lite graph may quantize near ties, but changing
            # tie-breaking here would be an unverified policy change.
            batch_actions = np.argmax(masked, axis=1)
            actions.extend(batch_actions.astype(np.int64).tolist())
            q_values.extend(output.tolist())
        return actions, q_values, mask_array.tolist(), [True] * obs_array.shape[0]
