# The models are header-only for now; this target carries their include path
# and the SystemC they need.
add_library(socpuppet_models INTERFACE)
target_include_directories(socpuppet_models INTERFACE ${PROJECT_SOURCE_DIR}/src)
target_link_libraries(socpuppet_models INTERFACE SystemC::systemc)

# The Python extension. It is the one binary in a Python process that embeds
# the SystemC kernel.
pybind11_add_module(_core bindings/core.cpp)
target_link_libraries(_core PRIVATE socpuppet_models)
# Emit the extension next to the Python sources so the package is importable
# straight from the source tree during development.
set_target_properties(_core PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY ${PROJECT_SOURCE_DIR}/python/socpuppet)
