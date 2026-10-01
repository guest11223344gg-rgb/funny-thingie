cmake_minimum_required(VERSION 3.21.0)
project(beamngweb_smoke CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(smoke main.cpp)

# The `-o` below is the single source of truth for the output name: emcc names
# the sibling .js/.wasm after the .html basename, so index.html yields
# index.js/index.wasm next to it. The page must be index.html because the dev
# server (tools/serve.py) serves build/web at "/".
target_link_options(smoke PRIVATE
    -sMIN_WEBGL_VERSION=2
    -sMAX_WEBGL_VERSION=2
    -sALLOW_MEMORY_GROWTH=1
    -sSTACK_SIZE=5242880
    --shell-file "${CMAKE_CURRENT_SOURCE_DIR}/shell.html"
    -o "${CMAKE_BINARY_DIR}/index.html"
)

# CMake unconditionally appends its own `-o <TARGET>` *after* the link options,
# and emcc honours the last `-o`. Left alone that trailing flag is `smoke.js`
# (CMAKE_EXECUTABLE_SUFFIX is .js for Emscripten), which wins and yields no
# index.html at all. Naming the executable's own output index.html here makes
# CMake's implicit `-o` agree with the explicit one above rather than fight it.
# The .html suffix must be set explicitly for the same reason.
set_target_properties(smoke PROPERTIES
    OUTPUT_NAME "index"
    SUFFIX ".html"
)
