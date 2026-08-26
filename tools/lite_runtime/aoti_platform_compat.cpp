// Minimal platform hooks needed by the libtorch-free AOTI CUDA shim.

#include <chrono>
#include <cstdio>
#include <cstdlib>

#include <executorch/runtime/platform/abort.h>
#include <executorch/runtime/platform/log.h>
#include <executorch/runtime/platform/platform.h>

extern "C" void et_pal_init(void) {}

namespace executorch::runtime {

[[noreturn]] void runtime_abort() {
  std::abort();
}

namespace internal {

et_timestamp_t get_log_timestamp() {
  using Clock = std::chrono::steady_clock;
  return static_cast<et_timestamp_t>(
      std::chrono::duration_cast<std::chrono::microseconds>(
          Clock::now().time_since_epoch())
          .count());
}

void vlogf(
    LogLevel,
    et_timestamp_t,
    const char* filename,
    const char* function,
    size_t line,
    const char* format,
    va_list args) {
  std::fprintf(
      stderr,
      "MortalSim AOTI: %s:%zu %s: ",
      filename != nullptr ? filename : "<unknown>",
      line,
      function != nullptr ? function : "<unknown>");
  std::vfprintf(stderr, format, args);
  std::fputc('\n', stderr);
}

} // namespace internal
} // namespace executorch::runtime
