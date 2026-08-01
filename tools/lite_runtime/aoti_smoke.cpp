#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cuda_runtime_api.h>

#include <chrono>
#include <cstring>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using Error = uint32_t;
using Tensor = void*;
using Container = void*;

template <typename Function>
Function load_symbol(HMODULE library, const char* name) {
  auto symbol = reinterpret_cast<Function>(GetProcAddress(library, name));
  if (symbol == nullptr) {
    throw std::runtime_error(std::string("missing symbol: ") + name);
  }
  return symbol;
}

void check(Error error, const char* operation) {
  if (error != 0) {
    throw std::runtime_error(
        std::string(operation) + " failed with code " + std::to_string(error));
  }
}

void check_cuda(cudaError_t error, const char* operation) {
  if (error != cudaSuccess) {
    throw std::runtime_error(
        std::string(operation) + " failed: " + cudaGetErrorString(error));
  }
}

std::vector<uint8_t> read_file(const char* path) {
  std::ifstream input(path, std::ios::binary | std::ios::ate);
  if (!input) {
    throw std::runtime_error(std::string("cannot open ") + path);
  }
  const auto size = input.tellg();
  std::vector<uint8_t> bytes(static_cast<size_t>(size));
  input.seekg(0);
  input.read(reinterpret_cast<char*>(bytes.data()), size);
  return bytes;
}

} // namespace

int main(int argc, char** argv) {
  if (argc != 4 && argc != 5 && argc != 8) {
    std::fprintf(
        stderr,
        "usage: aoti_smoke MODEL_DLL WEIGHTS_BLOB SHIM_DLL [BATCH [OBS MASK OUTPUT]]\n");
    return 2;
  }

  try {
    HMODULE shim = LoadLibraryA(argv[3]);
    if (shim == nullptr) {
      throw std::runtime_error("cannot load CUDA shim DLL");
    }
    HMODULE model = LoadLibraryA(argv[1]);
    if (model == nullptr) {
      throw std::runtime_error("cannot load model DLL");
    }

    using Create = Error (*)(Container*, size_t, const char*, const char*);
    using DeleteContainer = Error (*)(Container);
    using UpdateWeights = Error (*)(Container, const uint8_t*);
    using Run = Error (*)(Container, Tensor*, size_t, Tensor*, size_t, void*, void*);
    using LastError = Error (*)(const char**);
    using CreateTensor = Error (*)(
        void*, int64_t, const int64_t*, const int64_t*, int64_t, int32_t,
        int32_t, int32_t, Tensor*, int32_t, const uint8_t*, int64_t);
    using GetData = Error (*)(Tensor, void**);
    using DeleteTensor = Error (*)(Tensor);

    const auto create = load_symbol<Create>(model, "AOTInductorModelContainerCreateWithDevice");
    const auto delete_container = load_symbol<DeleteContainer>(model, "AOTInductorModelContainerDelete");
    const auto update_weights = load_symbol<UpdateWeights>(model, "AOTInductorModelUpdateConstantsFromBlob");
    const auto run = load_symbol<Run>(model, "AOTInductorModelContainerRunSingleThreaded");
    const auto last_error = load_symbol<LastError>(model, "AOTInductorGetLastError");
    const auto create_tensor = load_symbol<CreateTensor>(shim, "aoti_torch_create_tensor_from_blob_v2");
    const auto get_data = load_symbol<GetData>(shim, "aoti_torch_get_data_ptr");
    const auto delete_tensor = load_symbol<DeleteTensor>(shim, "aoti_torch_delete_tensor_object");

    Container container = nullptr;
    Error error = create(&container, 1, "cuda:0", "");
    if (error != 0) {
      const char* message = nullptr;
      last_error(&message);
      throw std::runtime_error(message != nullptr ? message : "container creation failed");
    }

    auto weights = read_file(argv[2]);
    check(update_weights(container, weights.data()), "load weights");

    const int64_t batch = argc >= 5 ? std::stoll(argv[4]) : 512;
    const size_t obs_count = static_cast<size_t>(batch) * 1012 * 34;
    const size_t mask_count = static_cast<size_t>(batch) * 46;
    const size_t output_count = static_cast<size_t>(batch) * 46;
    std::vector<float> host_obs(obs_count, 0.0f);
    std::vector<uint8_t> host_mask(mask_count, 1);
    std::vector<float> host_output(output_count);
    if (argc == 8) {
      auto obs_bytes = read_file(argv[5]);
      auto mask_bytes = read_file(argv[6]);
      if (obs_bytes.size() != host_obs.size() * sizeof(float) ||
          mask_bytes.size() != host_mask.size()) {
        throw std::runtime_error("input corpus has the wrong byte size");
      }
      std::memcpy(host_obs.data(), obs_bytes.data(), obs_bytes.size());
      std::memcpy(host_mask.data(), mask_bytes.data(), mask_bytes.size());
    }

    void* device_obs = nullptr;
    void* device_mask = nullptr;
    check_cuda(cudaMalloc(&device_obs, host_obs.size() * sizeof(float)), "cudaMalloc obs");
    check_cuda(cudaMalloc(&device_mask, host_mask.size()), "cudaMalloc mask");
    check_cuda(cudaMemcpy(device_obs, host_obs.data(), host_obs.size() * sizeof(float), cudaMemcpyHostToDevice), "copy obs");
    check_cuda(cudaMemcpy(device_mask, host_mask.data(), host_mask.size(), cudaMemcpyHostToDevice), "copy mask");
    cudaStream_t stream = nullptr;
    check_cuda(cudaStreamCreate(&stream), "create CUDA stream");

    const int64_t obs_sizes[] = {batch, 1012, 34};
    const int64_t obs_strides[] = {1012 * 34, 34, 1};
    const int64_t mask_sizes[] = {batch, 46};
    const int64_t mask_strides[] = {46, 1};

    auto invoke = [&]() {
      Tensor inputs[2] = {nullptr, nullptr};
      check(create_tensor(device_obs, 3, obs_sizes, obs_strides, 0, 6, 1, 0, &inputs[0], 0, nullptr, 0), "create obs tensor");
      check(create_tensor(device_mask, 2, mask_sizes, mask_strides, 0, 11, 1, 0, &inputs[1], 0, nullptr, 0), "create mask tensor");
      Tensor output = nullptr;
      Error run_error = run(
          container,
          inputs,
          2,
          &output,
          1,
          reinterpret_cast<void*>(stream),
          nullptr);
      if (run_error != 0) {
        const char* message = nullptr;
        last_error(&message);
        throw std::runtime_error(message != nullptr ? message : "model run failed");
      }
      void* output_data = nullptr;
      check(get_data(output, &output_data), "get output data");
      check_cuda(cudaStreamSynchronize(stream), "synchronize model stream");
      check_cuda(cudaMemcpy(host_output.data(), output_data, host_output.size() * sizeof(float), cudaMemcpyDeviceToHost), "copy output");
      check(delete_tensor(output), "delete output tensor");
    };

    for (int index = 0; index < 3; ++index) {
      invoke();
    }
    if (argc == 8) {
      std::ofstream output(argv[7], std::ios::binary);
      output.write(
          reinterpret_cast<const char*>(host_output.data()),
          static_cast<std::streamsize>(host_output.size() * sizeof(float)));
    }
    const auto start = std::chrono::steady_clock::now();
    constexpr int iterations = 20;
    for (int index = 0; index < iterations; ++index) {
      invoke();
    }
    const auto elapsed = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - start).count();
    std::printf(
        "batch=%lld mean_ms=%.3f obs_per_second=%.1f q0=%.6f\n",
        static_cast<long long>(batch),
        elapsed * 1000.0 / iterations,
        batch * iterations / elapsed,
        host_output[0]);

    cudaFree(device_mask);
    cudaFree(device_obs);
    cudaStreamDestroy(stream);
    check(delete_container(container), "delete container");
    FreeLibrary(model);
    FreeLibrary(shim);
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "%s\n", error.what());
    return 1;
  }
}
