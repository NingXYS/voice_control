cmake_minimum_required(VERSION 3.8)
project(voice_control)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(moveit_ros_planning_interface REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)

# JSON library
find_package(nlohmann_json 3.2.0 REQUIRED)

add_executable(robot_controller src/robot_controller.cpp)
ament_target_dependencies(robot_controller
  rclcpp
  std_msgs
  moveit_ros_planning_interface
  tf2
  tf2_ros
  tf2_geometry_msgs
)
target_link_libraries(robot_controller nlohmann_json::nlohmann_json)

install(TARGETS
  robot_controller
  DESTINATION lib/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/voice_qwen_llm.py
  scripts/voice_wake_entry.py
  scripts/build_wake_keyword.py
  DESTINATION lib/${PROJECT_NAME}
)

install(FILES
  scripts/voice_runtime_config.py
  scripts/voice_wake_word.py
  scripts/voice_command_vad.py
  scripts/voice_audio_session.py
  scripts/voice_prompt_tone.py
  scripts/voice_wake_runtime.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
