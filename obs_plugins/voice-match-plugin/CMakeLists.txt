cmake_minimum_required(VERSION 3.16...3.28)

include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/common/bootstrap.cmake" NO_POLICY_SCOPE)

project(voice-match VERSION 0.4.0)

option(ENABLE_FRONTEND_API "Use obs-frontend-api for UI functionality" OFF)
option(ENABLE_QT "Use Qt functionality" OFF)

include(compilerconfig)
include(defaults)
include(helpers)

add_library(${CMAKE_PROJECT_NAME} MODULE)

find_package(libobs REQUIRED)
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE OBS::libobs)

target_sources(
  ${CMAKE_PROJECT_NAME}
  PRIVATE
    src/plugin-main.c
    src/vm_filter.c
    src/vmcore/profile.c
)

# Include vmcore header-only library
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/src
  ${CMAKE_CURRENT_SOURCE_DIR}/src/vmcore
)

# Threading support
find_package(Threads REQUIRED)
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE Threads::Threads)

# Windows-specific: use MinGW or MSVC appropriately
if(MSVC)
  target_compile_options(${CMAKE_PROJECT_NAME} PRIVATE /W3)
  target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE _CRT_SECURE_NO_WARNINGS)
else()
  target_compile_options(${CMAKE_PROJECT_NAME} PRIVATE -Wall -Wno-unused-function)
endif()

set_target_properties_plugin(${CMAKE_PROJECT_NAME} PROPERTIES OUTPUT_NAME ${_name})
setup_plugin_target(${CMAKE_PROJECT_NAME})

# Install targets
install(TARGETS ${CMAKE_PROJECT_NAME}
  LIBRARY DESTINATION "${CMAKE_INSTALL_PLUGINS_DIR}"
)

install(DIRECTORY data/locale/
  DESTINATION "${CMAKE_INSTALL_LOCALE_DIR}"
)
