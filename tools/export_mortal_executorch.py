#!/usr/bin/env python3
"""Compile a Mortal v4 checkpoint with ExecuTorch's libtorch-free CUDA backend."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mortal"))
for extension_dir in (
    ROOT / "target" / "release",
    ROOT / "dist" / "MortalSim" / "_internal" / "target" / "release",
):
    if extension_dir.is_dir():
        sys.path.insert(0, str(extension_dir))
        break

from executorch.backends.cuda.cuda_backend import CudaBackend  # noqa: E402
from executorch.backends.cuda.cuda_partitioner import CudaPartitioner  # noqa: E402
from executorch.exir import EdgeCompileConfig, to_edge_transform_and_lower  # noqa: E402
from model import Brain, DQN  # noqa: E402


class MortalPolicy(torch.nn.Module):
    def __init__(self, brain: Brain, dqn: DQN, *, amp_static: bool = False, amp_autocast: bool = False) -> None:
        super().__init__()
        self.brain = brain
        self.dqn = dqn
        self.amp_static = amp_static
        self.amp_autocast = amp_autocast

    def forward(self, obs: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        if self.amp_autocast:
            # Keep parameters in their original fp32 form and let CUDA
            # autocast choose the same per-op dtypes as the reference engine.
            with torch.autocast("cuda", enabled=True):
                phi = self.brain(obs)
                q = self.dqn(phi, mask)
            return q.float()
        if self.amp_static:
            # Statically reproduce the current CUDA autocast policy: tensor
            # core layers consume fp16, batch-norm state stays fp32, and the
            # DQN reduction/final Q values are fp32.
            phi = self.brain(obs.to(torch.float16))
            value, advantage = self.dqn.net(phi).split((1, 46), dim=-1)
            advantage_sum = (
                advantage.masked_fill(~mask, 0.0).float().sum(-1, keepdim=True)
            )
            advantage_mean = advantage_sum / mask.sum(-1, keepdim=True)
            return (value.float() + advantage.float() - advantage_mean).masked_fill(
                ~mask, -torch.inf
            )
        return self.dqn(self.brain(obs), mask)


class MatmulConv1d(nn.Module):
    """Conv1d expressed as GEMM so the libtorch-free CUDA backend can lower it."""

    def __init__(self, source: nn.Conv1d) -> None:
        super().__init__()
        if source.dilation != (1,) or source.groups != 1:
            raise ValueError("Lite GEMM convolution only supports dilation=1 and groups=1")
        self.weight = nn.Parameter(source.weight.detach().clone(), requires_grad=False)
        self.bias = (
            nn.Parameter(source.bias.detach().clone(), requires_grad=False)
            if source.bias is not None
            else None
        )
        self.kernel_size = source.kernel_size[0]
        self.padding = source.padding[0]
        self.stride = source.stride[0]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = F.pad(x, (self.padding, self.padding))
        patches = x.unfold(2, self.kernel_size, self.stride)
        patches = patches.permute(0, 2, 1, 3).flatten(2)
        weight = self.weight.flatten(1).transpose(0, 1)
        output = torch.matmul(patches, weight)
        if self.bias is not None:
            output = output + self.bias
        return output.transpose(1, 2)


def replace_conv1d(module: nn.Module) -> None:
    for name, child in list(module.named_children()):
        if isinstance(child, nn.Conv1d):
            setattr(module, name, MatmulConv1d(child))
        else:
            replace_conv1d(child)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=512)
    parser.add_argument(
        "--precision", choices=("fp32", "amp-static", "amp-autocast"), default="fp32"
    )
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("ExecuTorch CUDA export requires an available CUDA GPU")
    # Inductor disables Triton template generation below 68 SMs because its
    # autotuning heuristic targets datacenter-sized GPUs. Lite must also build
    # on laptop GPUs; the generated kernels themselves support these devices.
    import torch._inductor.utils as inductor_utils

    inductor_utils.is_big_gpu = lambda _device=0: True
    if os.name == "nt":
        bundled_flatc = resources.files("executorch").joinpath("data/bin/flatc.exe")
        if bundled_flatc.is_file():
            os.environ.setdefault("FLATC_EXECUTABLE", str(bundled_flatc))
        # PyTorch 2.13's AOTInductor GPU wrapper still emits the GCC spelling
        # even when its host compiler is MSVC. Keep this exporter-local rather
        # than patching the installed torch package.
        original_writeline = inductor_utils.IndentedBuffer.writeline

        def msvc_writeline(self, line):
            if isinstance(line, str):
                line = line.replace(
                    "static __attribute__((noinline)) void",
                    "__declspec(noinline) static void",
                )
            return original_writeline(self, line)

        inductor_utils.IndentedBuffer.writeline = msvc_writeline

        # ExecuTorch 1.3 configures its shim only for Linux-to-Windows
        # cross-compilation. Native MSVC needs the same lightweight shim, but
        # must not enable the MinGW cross-target path. AOTInductor also omits
        # cudart from its native libtorch-free CUDA link line.
        import torch._inductor.cpp_builder as cpp_builder
        import torch._inductor.codecache as codecache

        shim_dir = str(resources.files("executorch").joinpath("data/lib"))
        original_torch_args = cpp_builder._get_torch_related_args
        original_device_options = cpp_builder.get_cpp_torch_device_options
        original_cache_write = codecache.write
        original_aot_compile = torch._inductor.aot_compile

        def native_windows_torch_args(include_pytorch, aot_mode):
            includes, library_dirs, libraries = original_torch_args(
                include_pytorch, aot_mode
            )
            if not torch._inductor.config.aot_inductor.link_libtorch:
                library_dirs.append(shim_dir)
                libraries.append("aoti_cuda_shims")
            return includes, library_dirs, libraries

        def native_windows_device_options(device_type, aot_mode=False, compile_only=False):
            result = list(
                original_device_options(device_type, aot_mode, compile_only)
            )
            if (
                device_type == "cuda"
                and not compile_only
                and not torch._inductor.config.aot_inductor.link_libtorch
            ):
                if "cudart" not in result[5]:
                    result[5].append("cudart")
            return tuple(result)

        def msvc_embed_cubins(cubins, output_dir, cpp_compiler="cl"):
            """Embed cubins as COFF data arrays; MSVC cannot assemble .incbin."""
            source_path = Path(output_dir) / "cubins_combined.cpp"
            object_path = Path(output_dir) / "cubins_combined.obj"
            with source_path.open("w", encoding="ascii", newline="\n") as source:
                source.write('extern "C" {\n')
                for cubin_path, kernel_name in cubins:
                    payload = Path(cubin_path).read_bytes()
                    source.write(
                        "__declspec(align(16)) extern const unsigned char "
                        f"__{kernel_name}_start[] = {{\n"
                    )
                    for offset in range(0, len(payload), 24):
                        source.write(
                            ",".join(str(value) for value in payload[offset : offset + 24])
                            + ",\n"
                        )
                    source.write("};\n")
                source.write("}\n")
            subprocess.run(
                [
                    cpp_compiler,
                    "/nologo",
                    "/c",
                    "/O2",
                    str(source_path),
                    f"/Fo{object_path}",
                ],
                check=True,
            )
            return str(object_path)

        def msvc_cache_write(
            content,
            extension,
            extra="",
            hash_type="code",
            specified_dir="",
            key=None,
        ):
            # Native Windows is excluded from AOTInductor's ELF `.incbin`
            # path. Put the same cubins in the already compiled kernel TU.
            if extension == "kernel.cpp" and isinstance(content, str):
                # ExecuTorch 1.3's prebuilt CUDA shim predates the get_numel
                # ABI added by torch 2.13. Supply that tiny compatibility
                # entry point from ABI calls which exist in both versions.
                content += r'''
#include <cstdint>
extern "C" {
struct AtenTensorOpaque;
using AtenTensorHandle = AtenTensorOpaque*;
using AOTITorchError = int32_t;
__declspec(dllimport) AOTITorchError aoti_torch_get_dim(
    AtenTensorHandle tensor, int64_t* ret_dim);
__declspec(dllimport) AOTITorchError aoti_torch_get_sizes(
    AtenTensorHandle tensor, int64_t** ret_sizes);

__declspec(dllexport) AOTITorchError aoti_torch_get_numel(
    AtenTensorHandle tensor, int64_t* ret_numel) {
  int64_t dim = 0;
  int64_t* sizes = nullptr;
  AOTITorchError error = aoti_torch_get_dim(tensor, &dim);
  if (error != 0) {
    return error;
  }
  error = aoti_torch_get_sizes(tensor, &sizes);
  if (error != 0) {
    return error;
  }
  int64_t numel = 1;
  for (int64_t index = 0; index < dim; ++index) {
    numel *= sizes[index];
  }
  *ret_numel = numel;
  return 0;
}

__declspec(dllexport) int32_t aoti_torch_dtype_float16() {
  return 5;
}
}
'''
                embedded = []
                active_kernels = getattr(
                    codecache.V.graph.wrapper_code, "_kernel_name_to_body", {}
                )
                for kernel_name, params in codecache.CudaKernelParamCache.cache.items():
                    if kernel_name not in active_kernels:
                        continue
                    cubin_path = params.get(codecache.get_cpp_wrapper_cubin_path_name())
                    if not cubin_path or not Path(cubin_path).is_file():
                        continue
                    payload = Path(cubin_path).read_bytes()
                    rows = []
                    for offset in range(0, len(payload), 24):
                        rows.append(
                            ",".join(
                                str(value) for value in payload[offset : offset + 24]
                            )
                            + ","
                        )
                    embedded.append(
                        'extern "C" __declspec(align(16)) extern const unsigned char '
                        f"__{kernel_name}_start[] = {{\n"
                        + "\n".join(rows)
                        + "\n};\n"
                    )
                if embedded:
                    content += "\n" + "".join(embedded)
            return original_cache_write(
                content, extension, extra, hash_type, specified_dir, key
            )

        cpp_builder._get_torch_related_args = native_windows_torch_args
        cpp_builder.get_cpp_torch_device_options = native_windows_device_options
        codecache.batch_convert_cubins_to_obj = msvc_embed_cubins
        codecache.write = msvc_cache_write

        def windows_aot_compile(*compile_args, **compile_kwargs):
            paths = original_aot_compile(*compile_args, **compile_kwargs)
            if isinstance(paths, list):
                rewritten = list(paths)
                for path in paths:
                    if path.endswith(".wrapper.pyd"):
                        so_path = path[: -len(".wrapper.pyd")] + ".wrapper.so"
                        shutil.copyfile(path, so_path)
                        rewritten.append(so_path)
                return rewritten
            return paths

        # The ExecuTorch packer recognizes only the Unix suffix although the
        # named blob is platform-neutral. Preserve the PE file and present a
        # temporary .so alias to its path scanner.
        torch._inductor.aot_compile = windows_aot_compile
    state = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    config = state["config"]
    version = int(config["control"]["version"])
    if version != 4:
        raise ValueError(f"Lite prototype currently supports Mortal v4, got v{version}")

    brain = Brain(
        version=version,
        conv_channels=int(config["resnet"]["conv_channels"]),
        num_blocks=int(config["resnet"]["num_blocks"]),
    ).eval()
    dqn = DQN(version=version).eval()
    brain.load_state_dict(state["mortal"], strict=True)
    dqn.load_state_dict(state["current_dqn"], strict=True)
    amp_static = args.precision == "amp-static"
    amp_autocast = args.precision == "amp-autocast"
    if amp_static:
        brain.half()
        dqn.half()
        for module in brain.modules():
            if isinstance(module, nn.BatchNorm1d):
                module.float()
    policy = MortalPolicy(brain, dqn, amp_static=amp_static, amp_autocast=amp_autocast).eval()
    # The CUDA backend can lower native Conv1d on recent ExecuTorch builds.
    # Keep the explicit GEMM lowering as the portable fallback, but allow a
    # parity probe with the native operator because cuDNN's accumulation order
    # is closer to the PyTorch AMP reference than a hand-expanded unfold.
    if os.environ.get("MORTALSIM_LITE_NATIVE_CONV") != "1":
        replace_conv1d(policy)

    obs = torch.zeros((args.batch, 1012, 34), dtype=torch.float32)
    mask = torch.ones((args.batch, 46), dtype=torch.bool)
    exported = torch.export.export(policy, (obs, mask), strict=True)
    compile_specs = [CudaBackend.generate_method_name_compile_spec("forward")]
    edge = to_edge_transform_and_lower(
        exported,
        partitioner=[CudaPartitioner(compile_specs)],
        compile_config=EdgeCompileConfig(_check_ir_validity=False),
    )
    program = edge.to_executorch()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "amp" if amp_static else "fp32"
    pte_path = args.output_dir / f"mortal-v4-{suffix}-b{args.batch}.pte"
    with pte_path.open("wb") as output:
        program.write_to_file(output)
    program.write_tensor_data_to_file(args.output_dir)

    print(f"Wrote {pte_path} ({pte_path.stat().st_size / 1024 / 1024:.1f} MiB)")
    for data_path in sorted(args.output_dir.glob("*.ptd")):
        print(f"Wrote {data_path} ({data_path.stat().st_size / 1024 / 1024:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
