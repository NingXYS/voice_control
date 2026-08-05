cmake_minimum_required(VERSION 3.8)
project(voice_control)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)

# This migration package publishes the stable robot_command JSON topic only.
# Motion planning, collision/workspace limits and emergency stop belong to the
# separately deployed controller and are intentionally not built from this tree.

install(PROGRAMS
  scripts/voice_wake_entry.py
  scripts/voice_space_wake.py
  scripts/voice_tts_node.py
  scripts/build_wake_keyword.py
  scripts/kws_sweep.py
  scripts/eval_kws.py
  scripts/voice_capture_smoke.py
  scripts/voice_ui_server.py
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
  scripts/voice_assembly_controller.py
  scripts/voice_massage_controller.py
  scripts/voice_online_services.py
  scripts/voice_massage_dry_run.py
  scripts/voice_qwen_llm.py
  scripts/latency_metrics.py
  scripts/voice_ui_events.py
  scripts/voice_subprocess.py
  scripts/voice_action_audit.py
  scripts/voice_network_policy.py
  DESTINATION lib/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/run_voice_ui.sh
  DESTINATION lib/${PROJECT_NAME}
)

install(
  DIRECTORY voice_ui/
  DESTINATION share/${PROJECT_NAME}/voice_ui
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
