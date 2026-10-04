# core/: plain C++ with no simulator underneath. Linking only this target is
# what keeps SystemC out of the kernel-free unit tests.
add_library(socpuppet_core INTERFACE)
target_include_directories(socpuppet_core INTERFACE ${PROJECT_SOURCE_DIR}/src)

# models/: the SystemC wrappers. platform/: composing them by name (ports,
# the registry, the platform builder). Header-only for now.
add_library(socpuppet_models INTERFACE)
target_link_libraries(socpuppet_models INTERFACE socpuppet_core scc::components SystemC::systemc)

# The Python extension. It is the one binary in a Python process that embeds
# the SystemC kernel.
pybind11_add_module(_core bindings/core.cpp)
target_link_libraries(_core PRIVATE socpuppet_models)
if(SKBUILD)
  # Building a wheel: the extension goes inside the installed package.
  install(TARGETS _core LIBRARY DESTINATION socpuppet)
else()
  # Development: emit the extension next to the Python sources so the package
  # is importable straight from the source tree.
  set_target_properties(_core PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY ${PROJECT_SOURCE_DIR}/python/socpuppet)
endif()
