cmake_minimum_required(VERSION 3.16)
project(CapstoneProject LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# repo root (one level up from scripts/)
set(ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)

add_executable(capstone
  ${ROOT}/src/main.cpp
  ${ROOT}/src/car/functions/init.cpp
)

target_include_directories(capstone PRIVATE
  ${ROOT}/src
  ${ROOT}/src/car/headers
)
