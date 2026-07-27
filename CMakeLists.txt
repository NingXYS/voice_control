cmake_minimum_required(VERSION 3.8)
project(voice_control)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
option(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER "Build the robot controller executable" ON)

if(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER)
  find_package(rclcpp REQUIRED)
  find_package(std_msgs REQUIRED)
  find_package(moveit_ros_planning_interface REQUIRED)
  find_package(tf2 REQUIRED)
  find_package(tf2_ros REQUIRED)
  find_package(tf2_geometry_msgs REQUIRED)
  find_package(nlohmann_json 3.2.0 REQUIRED)
  add_executable(robot_controller src/robot_controller.cpp)
  ament_target_dependencies(robot_controller rclcpp std_msgs moveit_ros_planning_interface tf2 tf2_ros tf2_geometry_msgs)
  target_link_libraries(robot_controller nlohmann_json::nlohmann_json)
  install(TARGETS robot_controller DESTINATION lib/${PROJECT_NAME})
endif()

install(PROGRAMS
  scripts/voice_wake_entry.py
  scripts/voice_space_wake.py
  scripts/voice_tts_node.py
  scripts/build_wake_keyword.py
  scripts/kws_sweep.py
  scripts/eval_kws.py
  scripts/voice_capture_smoke.py
  DESTINATION lib/${PROJECT_NAME}
)

install(FILES
  scripts/voice_runtime_config.py
  scripts/voice_wake_word.py
  scripts/voice_wake_verifier.py
  scripts/voice_command_vad.py
  scripts/voice_asr_wake_word.py
  scripts/voice_audio_session.py
  scripts/voice_capture_adapter.py
  scripts/voice_audio_frontend.py
  scripts/voice_prompt_tone.py
  scripts/voice_wake_runtime.py
  scripts/voice_tts.py
  scripts/voice_dialogue_backend.py
  scripts/voice_text_segmenter.py
  scripts/voice_asr_backend.py
  scripts/voice_tts_backend.py
  scripts/voice_runtime_container.py
  scripts/voice_text_pipeline.py
  scripts/voice_command_validation.py
  scripts/voice_robot_executor.py
  scripts/voice_local_knowledge.py
  scripts/voice_llm_client.py
  scripts/voice_qwen_llm.py
  scripts/latency_metrics.py
  DESTINATION lib/${PROJECT_NAME}
)

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/knowledge_base")
  install(
    DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/knowledge_base/"
    DESTINATION lib/knowledge_base
  )
endif()

set(MODEL_ASSET_DIR "${CMAKE_CURRENT_SOURCE_DIR}/models")
if(EXISTS "${MODEL_ASSET_DIR}")
  install(
    DIRECTORY "${MODEL_ASSET_DIR}/"
    DESTINATION lib/${PROJECT_NAME}/models
    PATTERN ".git" EXCLUDE
  )
else()
  message(FATAL_ERROR "Required model assets are missing: ${MODEL_ASSET_DIR}")
endif()

ament_package()
