#include <atomic>
#include <cstdio>
#include <thread>

extern "C" float guSqrtf(float value);

int main() {
    std::atomic<int> result{0};
    std::thread worker([&result] {
        result.store(guSqrtf(81.0f) == 9.0f ? 42 : -1);
    });
    worker.join();
    if (result.load() != 42) {
        std::fputs("FAIL: game math / pthread probe\n", stderr);
        return 1;
    }
    std::puts("PASS: WASM C11 game math + C++20 + pthread execution (Node only; not the game)");
    return 0;
}
