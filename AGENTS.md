# Project Rules for Voice Robot Optimization

## Main goal

Optimize response latency for the voice-controlled ROS2 robotic arm system.

## Important constraints

- This project is developed on a PC but will eventually run on the robotic arm hardware.
- Do not optimize only for the development PC if the change would make deployment harder.
- Preserve the current behavior of voice command parsing, ROS2 publishing, Dify fallback, Ollama fallback, and TTS replies unless the plan explicitly changes them.
- Safety-related robot behavior must not be changed without an explicit plan and review.

## Reference code policy

- `reference/` contains external case-study code.
- Agents may read files under `reference/`.
- Agents must not modify files under `reference/`.
- Reference code is only for learning architecture, latency optimization, audio pipeline design, async design, ROS2 integration, and model invocation patterns.
- Do not copy large blocks directly from reference code.
- Adapt patterns to this project's existing architecture.

## Optimization policy

- Before optimizing, add timing instrumentation.
- Every latency optimization must be measured before and after.
- Prefer staged changes:
  1. instrumentation
  2. low-risk local shortcuts
  3. async pipeline improvements
  4. model/prompt/RAG optimization
  5. architecture-level refactor
- Do not modify mechanical-arm control semantics without GPT review.
