# cmake/toolchains/emscripten.cmake
# Wraps the toolchain that ships inside the Emscripten SDK, so callers do not
# need to know where the SDK was activated.
if(NOT DEFINED ENV{EMSDK})
    message(FATAL_ERROR "EMSDK is not set. Source emsdk_env.sh, or run from emcmdprompt.")
endif()

include("$ENV{EMSDK}/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake")

# WebGL2 == OpenGL ES 3.0. Torque3D's shader generator must emit ES 3.00
# source, so pin the whole project to that level rather than letting SDL or
# Emscripten negotiate something weaker.
set(CMAKE_CXX_STANDARD 17 CACHE STRING "" FORCE)
add_compile_options(-sMIN_WEBGL_VERSION=2 -sMAX_WEBGL_VERSION=2)
