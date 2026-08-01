#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cuda_runtime_api.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace {

using Error = uint32_t;
using Tensor = void*;
using Container = void*;

template <typename Function>
Function load_symbol(HMODULE library, const char* name) {
  return reinterpret_cast<Function>(GetProcAddress(library, name));
}

struct Runtime {
  HMODULE shim = nullptr;
  HMODULE model = nullptr;
  Container container = nullptr;
  cudaStream_t stream = nullptr;
  void* device_obs = nullptr;
  void* device_mask = nullptr;
  int64_t capacity = 0;
  std::vector<float> host_obs;
  std::vector<uint8_t> host_mask;
  std::vector<float> host_output;

  using DeleteContainer = Error (*)(Container);
  using UpdateWeights = Error (*)(Container, const uint8_t*);
  using Run = Error (*)(Container, Tensor*, size_t, Tensor*, size_t, void*, void*);
  using LastError = Error (*)(const char**);
  using CreateTensor = Error (*)(
      void*, int64_t, const int64_t*, const int64_t*, int64_t, int32_t,
      int32_t, int32_t, Tensor*, int32_t, const uint8_t*, int64_t);
  using GetData = Error (*)(Tensor, void**);
  using DeleteTensor = Error (*)(Tensor);
  using GetNumConstants = Error (*)(Container, size_t*);
  using GetConstantName = Error (*)(Container, size_t, const char**);
  using GetConstantDtype = Error (*)(Container, size_t, int32_t*);
  using UpdatePairs = Error (*)(Container, const void*, size_t, bool, bool);

  DeleteContainer delete_container = nullptr;
  UpdateWeights update_weights = nullptr;
  Run run = nullptr;
  LastError last_error = nullptr;
  CreateTensor create_tensor = nullptr;
  GetData get_data = nullptr;
  DeleteTensor delete_tensor = nullptr;
  GetNumConstants get_num_constants = nullptr;
  GetConstantName get_constant_name = nullptr;
  GetConstantDtype get_constant_dtype = nullptr;
  UpdatePairs update_pairs = nullptr;
  std::vector<uint8_t> weights;

  ~Runtime() {
    if (container != nullptr && delete_container != nullptr) {
      delete_container(container);
    }
    if (device_mask != nullptr) {
      cudaFree(device_mask);
    }
    if (device_obs != nullptr) {
      cudaFree(device_obs);
    }
    if (stream != nullptr) {
      cudaStreamDestroy(stream);
    }
    if (model != nullptr) {
      FreeLibrary(model);
    }
    if (shim != nullptr) {
      FreeLibrary(shim);
    }
  }
};

void set_error(char* buffer, size_t buffer_size, const std::string& message) {
  if (buffer == nullptr || buffer_size == 0) {
    return;
  }
  std::strncpy(buffer, message.c_str(), buffer_size - 1);
  buffer[buffer_size - 1] = '\0';
}

struct LiteTensorInput {
  const char* name;
  const void* data;
  int32_t ndim;
  int64_t sizes[8];
  int64_t strides[8];
  int32_t dtype;
};

struct ConstantPair {
  const char* name;
  Tensor handle;
};

bool check_cuda(cudaError_t error, char* buffer, size_t buffer_size, const char* operation) {
  if (error == cudaSuccess) {
    return true;
  }
  set_error(
      buffer,
      buffer_size,
      std::string(operation) + ": " + cudaGetErrorString(error));
  return false;
}

bool check_error(Error error, Runtime* runtime, char* buffer, size_t buffer_size, const char* operation) {
  if (error == 0) {
    return true;
  }
  const char* detail = nullptr;
  if (runtime != nullptr && runtime->last_error != nullptr) {
    runtime->last_error(&detail);
  }
  set_error(
      buffer,
      buffer_size,
      std::string(operation) + " failed" +
          (detail != nullptr ? std::string(": ") + detail : ""));
  return false;
}

std::vector<uint8_t> read_file(const char* path) {
  std::ifstream input(path, std::ios::binary | std::ios::ate);
  if (!input) {
    return {};
  }
  const auto size = input.tellg();
  if (size <= 0) {
    return {};
  }
  std::vector<uint8_t> bytes(static_cast<size_t>(size));
  input.seekg(0);
  input.read(reinterpret_cast<char*>(bytes.data()), size);
  return bytes;
}

} // namespace

extern "C" {

__declspec(dllexport) void* mortal_lite_create(
    const char* model_path,
    const char* weights_path,
    const char* shim_path,
    int64_t batch_capacity,
    char* error,
    size_t error_size) {
  if (model_path == nullptr || shim_path == nullptr ||
      batch_capacity <= 0) {
    set_error(error, error_size, "invalid Lite runtime arguments");
    return nullptr;
  }

  auto runtime = std::make_unique<Runtime>();
  runtime->capacity = batch_capacity;
  runtime->shim = LoadLibraryExA(shim_path, nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
  if (runtime->shim == nullptr) {
    set_error(error, error_size, "unable to load aoti_cuda_shims.dll");
    return nullptr;
  }
  runtime->model = LoadLibraryExA(model_path, nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
  if (runtime->model == nullptr) {
    set_error(error, error_size, "unable to load Lite model DLL");
    return nullptr;
  }

  using Create = Error (*)(Container*, size_t, const char*, const char*);
  const auto create = load_symbol<Create>(runtime->model, "AOTInductorModelContainerCreateWithDevice");
  runtime->delete_container = load_symbol<Runtime::DeleteContainer>(runtime->model, "AOTInductorModelContainerDelete");
  runtime->update_weights = load_symbol<Runtime::UpdateWeights>(runtime->model, "AOTInductorModelUpdateConstantsFromBlob");
  runtime->run = load_symbol<Runtime::Run>(runtime->model, "AOTInductorModelContainerRunSingleThreaded");
  runtime->last_error = load_symbol<Runtime::LastError>(runtime->model, "AOTInductorGetLastError");
  runtime->get_num_constants = load_symbol<Runtime::GetNumConstants>(runtime->model, "AOTInductorModelContainerGetNumConstants");
  runtime->get_constant_name = load_symbol<Runtime::GetConstantName>(runtime->model, "AOTInductorModelContainerGetConstantName");
  runtime->get_constant_dtype = load_symbol<Runtime::GetConstantDtype>(runtime->model, "AOTInductorModelContainerGetConstantDtype");
  runtime->update_pairs = load_symbol<Runtime::UpdatePairs>(runtime->model, "AOTInductorModelContainerUpdateConstantBufferFromCpuPairs");
  runtime->create_tensor = load_symbol<Runtime::CreateTensor>(runtime->shim, "aoti_torch_create_tensor_from_blob_v2");
  runtime->get_data = load_symbol<Runtime::GetData>(runtime->shim, "aoti_torch_get_data_ptr");
  runtime->delete_tensor = load_symbol<Runtime::DeleteTensor>(runtime->shim, "aoti_torch_delete_tensor_object");
  if (create == nullptr || runtime->delete_container == nullptr ||
      runtime->update_weights == nullptr || runtime->run == nullptr ||
      runtime->last_error == nullptr || runtime->create_tensor == nullptr ||
      runtime->get_data == nullptr || runtime->delete_tensor == nullptr ||
      runtime->get_num_constants == nullptr || runtime->get_constant_name == nullptr ||
      runtime->get_constant_dtype == nullptr || runtime->update_pairs == nullptr) {
    set_error(error, error_size, "Lite runtime DLL is missing an AOTI symbol");
    return nullptr;
  }

  Error result = create(&runtime->container, 1, "cuda:0", "");
  if (!check_error(result, runtime.get(), error, error_size, "create Lite model")) {
    return nullptr;
  }
  if (weights_path != nullptr && weights_path[0] != '\0') {
    runtime->weights = read_file(weights_path);
    if (runtime->weights.empty() ||
        !check_error(
            runtime->update_weights(runtime->container, runtime->weights.data()),
            runtime.get(),
            error,
            error_size,
            "load Lite weights")) {
      return nullptr;
    }
  }

  const size_t obs_count = static_cast<size_t>(batch_capacity) * 1012 * 34;
  const size_t mask_count = static_cast<size_t>(batch_capacity) * 46;
  runtime->host_obs.resize(obs_count);
  runtime->host_mask.resize(mask_count, 1);
  runtime->host_output.resize(static_cast<size_t>(batch_capacity) * 46);
  if (!check_cuda(cudaStreamCreate(&runtime->stream), error, error_size, "create CUDA stream") ||
      !check_cuda(cudaMalloc(&runtime->device_obs, obs_count * sizeof(float)), error, error_size, "allocate obs") ||
      !check_cuda(cudaMalloc(&runtime->device_mask, mask_count), error, error_size, "allocate mask")) {
    return nullptr;
  }
  return runtime.release();
}

__declspec(dllexport) int mortal_lite_constant_count(void* handle) {
  auto* runtime = static_cast<Runtime*>(handle);
  size_t count = 0;
  return runtime == nullptr || runtime->get_num_constants(runtime->container, &count) != 0
      ? -1 : static_cast<int>(count);
}

__declspec(dllexport) int mortal_lite_constant_info(
    void* handle,
    int index,
    char* name,
    size_t name_size,
    int* dtype) {
  auto* runtime = static_cast<Runtime*>(handle);
  if (runtime == nullptr || index < 0 || name == nullptr || name_size == 0) {
    return 1;
  }
  const char* source_name = nullptr;
  int32_t source_dtype = 0;
  if (runtime->get_constant_name(runtime->container, static_cast<size_t>(index), &source_name) != 0 ||
      runtime->get_constant_dtype(runtime->container, static_cast<size_t>(index), &source_dtype) != 0 ||
      source_name == nullptr) {
    return 1;
  }
  std::strncpy(name, source_name, name_size - 1);
  name[name_size - 1] = '\0';
  if (dtype != nullptr) {
    *dtype = source_dtype;
  }
  return 0;
}

__declspec(dllexport) int mortal_lite_update_constants(
    void* handle,
    const LiteTensorInput* inputs,
    size_t input_count,
    char* error,
    size_t error_size) {
  auto* runtime = static_cast<Runtime*>(handle);
  if (runtime == nullptr || inputs == nullptr || input_count == 0) {
    set_error(error, error_size, "invalid Lite constant update arguments");
    return 1;
  }
  std::vector<Tensor> tensors(input_count, nullptr);
  std::vector<ConstantPair> pairs(input_count);
  for (size_t index = 0; index < input_count; ++index) {
    const auto& input = inputs[index];
    if (input.name == nullptr || input.data == nullptr || input.ndim < 0 || input.ndim > 8) {
      set_error(error, error_size, "invalid Lite constant metadata");
      return 1;
    }
    Error result = runtime->create_tensor(
        const_cast<void*>(input.data),
        input.ndim,
        input.sizes,
        input.strides,
        0,
        input.dtype,
        0,
        0,
        &tensors[index],
        0,
        nullptr,
        0);
    if (!check_error(result, runtime, error, error_size, "create CPU constant tensor")) {
      for (size_t cleanup = 0; cleanup < index; ++cleanup) {
        runtime->delete_tensor(tensors[cleanup]);
      }
      return 1;
    }
    pairs[index] = {input.name, tensors[index]};
  }
  Error result = runtime->update_pairs(
      runtime->container,
      pairs.data(),
      pairs.size(),
      false,
      true);
  for (Tensor tensor : tensors) {
    runtime->delete_tensor(tensor);
  }
  return check_error(result, runtime, error, error_size, "update Lite constants") ? 0 : 1;
}

__declspec(dllexport) int mortal_lite_run(
    void* handle,
    const float* obs,
    const uint8_t* mask,
    int64_t batch,
    float* output,
    char* error,
    size_t error_size) {
  auto* runtime = static_cast<Runtime*>(handle);
  if (runtime == nullptr || obs == nullptr || mask == nullptr || output == nullptr ||
      batch <= 0 || batch > runtime->capacity) {
    set_error(error, error_size, "invalid Lite inference arguments");
    return 1;
  }
  const size_t obs_stride = 1012 * 34;
  const size_t mask_stride = 46;
  const size_t actual_obs = static_cast<size_t>(batch) * obs_stride;
  const size_t actual_mask = static_cast<size_t>(batch) * mask_stride;
  std::memcpy(runtime->host_obs.data(), obs, actual_obs * sizeof(float));
  std::memcpy(runtime->host_mask.data(), mask, actual_mask);
  std::fill(runtime->host_obs.begin() + actual_obs, runtime->host_obs.end(), 0.0f);
  std::fill(runtime->host_mask.begin() + actual_mask, runtime->host_mask.end(), 1);
  if (!check_cuda(
          cudaMemcpyAsync(
              runtime->device_obs,
              runtime->host_obs.data(),
              runtime->host_obs.size() * sizeof(float),
              cudaMemcpyHostToDevice,
              runtime->stream),
          error,
          error_size,
          "copy observations") ||
      !check_cuda(
          cudaMemcpyAsync(
              runtime->device_mask,
              runtime->host_mask.data(),
              runtime->host_mask.size(),
              cudaMemcpyHostToDevice,
              runtime->stream),
          error,
          error_size,
          "copy action mask")) {
    return 1;
  }

  const int64_t capacity = runtime->capacity;
  const int64_t obs_sizes[] = {capacity, 1012, 34};
  const int64_t obs_strides[] = {1012 * 34, 34, 1};
  const int64_t mask_sizes[] = {capacity, 46};
  const int64_t mask_strides[] = {46, 1};
  Tensor inputs[2] = {nullptr, nullptr};
  if (!check_error(
          runtime->create_tensor(
              runtime->device_obs,
              3,
              obs_sizes,
              obs_strides,
              0,
              6,
              1,
              0,
              &inputs[0],
              0,
              nullptr,
              0),
          runtime,
          error,
          error_size,
          "create observation tensor") ||
      !check_error(
          runtime->create_tensor(
              runtime->device_mask,
              2,
              mask_sizes,
              mask_strides,
              0,
              11,
              1,
              0,
              &inputs[1],
              0,
              nullptr,
              0),
          runtime,
          error,
          error_size,
          "create mask tensor")) {
    return 1;
  }

  Tensor result = nullptr;
  if (!check_error(
          runtime->run(
              runtime->container,
              inputs,
              2,
              &result,
              1,
              reinterpret_cast<void*>(runtime->stream),
              nullptr),
          runtime,
          error,
          error_size,
          "run Lite model") ||
      !check_cuda(
          cudaStreamSynchronize(runtime->stream),
          error,
          error_size,
          "synchronize Lite model")) {
    return 1;
  }
  void* result_data = nullptr;
  if (!check_error(
          runtime->get_data(result, &result_data),
          runtime,
          error,
          error_size,
          "read Lite output") ||
      !check_cuda(
          cudaMemcpy(
              output,
              result_data,
              static_cast<size_t>(batch) * 46 * sizeof(float),
              cudaMemcpyDeviceToHost),
          error,
          error_size,
          "copy Lite output")) {
    runtime->delete_tensor(result);
    return 1;
  }
  runtime->delete_tensor(result);
  return 0;
}

__declspec(dllexport) void mortal_lite_destroy(void* handle) {
  delete static_cast<Runtime*>(handle);
}

} // extern "C"
