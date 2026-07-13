---
slug: xiaozhi-inspired-voice-migration
status: drafting
intent: unclear
review_required: false
pending-action: write and review .ai/plans/xiaozhi-inspired-voice-migration.md
approach: one combined migration plan, ordered as environment isolation -> reproducible local wake loop -> service routing -> clean-clone cost and rollback proof
---

# Draft: xiaozhi-inspired-voice-migration

## Components (topology ledger)
| id | outcome | status | evidence |
| --- | --- | --- | --- |
| C1 | Voice-only build reaches a durable prefix without controller-only dependencies | active | `CMakeLists.txt:8-33`; clean-build cache `/tmp/voice_control_build13/voice_control/CMakeCache.txt` |
| C2 | One ROS-compatible Python 3.10 import graph with user-site disabled | active | current runtime probes; `/home/ning/voice_control_env.sh` |
| C3 | Models, audio tools and host profile are declared and preflighted | active | `scripts/voice_runtime_config.py:4-56`; asset inventory |
| C4 | Headless ASR/KWS/VAD/TTS wake loop remains host-native | active | `scripts/voice_wake_entry.py:43-157`; `scripts/voice_tts.py:11-94` |
| C5 | Local deterministic routing precedes configured Dify, then Ollama fallback | active | `scripts/voice_qwen_llm.py:269-342`; `scripts/voice_llm_client.py:825-852` |
| C6 | Clean-clone migration, no-motion QA, release and rollback are measurable | active | `.gitignore:45-58`; project `.ai/` workflow |

## Open assumptions (announced defaults)
| assumption | adopted default | rationale | reversible? |
| --- | --- | --- | --- |
| XiaoZhi adoption | borrow profiles, compatibility gates and release discipline only | ESP-IDF/embedded transports do not fit ROS2 Linux | yes |
| controller ownership | `VOICE_CONTROL_BUILD_ROBOT_CONTROLLER` defaults ON; voice build passes OFF | preserves existing package behavior while isolating voice work | yes |
| Python | isolated CPython 3.10 venv plus only configured ROS Python paths and `PYTHONNOUSERSITE=1` | matches ROS Humble ABI without exposing unrelated system/user packages | yes |
| runtime layout | fixed sibling roots `voice_control_build`, `voice_control_install`, `voice_control_runtime` | matches user-selected durable prefix direction and separates code/assets | yes |
| inference placement | ASR/KWS/VAD/TTS stay host-native; Dify/Ollama remain HTTP services | avoids latency and migration expansion | yes |
| QA | fake/in-memory publisher for behavior; real host checks stop before ROS graph/action publication | respects mechanical-arm ownership and safety | yes |
| packaging | asset manifest plus copied/checksummed runtime assets, not ignored source-tree state | clean clone must be sufficient when paired with declared asset input | yes |

## Findings (cited - path:lines)
- `CMakeLists.txt:8-33` unconditionally discovers MoveIt/TF/nlohmann and builds `robot_controller`; Python voice scripts are installed separately at `CMakeLists.txt:35-54`.
- `package.xml:12-22` mixes voice and controller dependencies; the plan leaves it unchanged and does not use full-package rosdep as the voice bootstrap contract.
- Current successful build used `/usr/bin` compilers/Python and system OpenSSL, but nlohmann CMake metadata from Miniconda. The durable prefix does not yet exist.
- Current base shell is Conda Python 3.13 and cannot load ROS Humble CPython 3.10 `rclpy`; the sourced venv is CPython 3.10 but imports numpy/soundfile/sherpa from user-site.
- `scripts/voice_runtime_config.py:4-28` defines model/audio settings but only validates scalar values at `:30-56`, not file presence, import origins or ALSA readiness.
- `scripts/voice_wake_entry.py:43-66` already avoids headless `pynput` import; regression coverage exists at `tests/test_wake_entry_regressions.py:16-55`.
- Current configured Paraformer and KWS directories are empty; usable models exist elsewhere. VAD exists. TTS is ignored by Git at `.gitignore:58` but installed by `CMakeLists.txt:57-61`.
- `scripts/voice_qwen_llm.py:335-342` blocks entry into `llm_parse` on Ollama health, even though `scripts/voice_llm_client.py:825-852` correctly implements configured Dify before Ollama.

## Decisions (with rationale)
- Formal plan lives in `.ai/plans/` because project `AGENTS.md` overrides the skill's default plan directory; `.omo/drafts/` remains planner state only.
- Do not modify, move, format, read for implementation, or test against `src/robot_controller.cpp`.
- Do not change `package.xml` in this effort. Voice-only bootstrap uses explicit voice manifests; controller dependency ownership remains untouched.
- Add only one CMake public option: `VOICE_CONTROL_BUILD_ROBOT_CONTROLLER`, default `ON`; wrap controller-only discovery, target, and target install. All Python installs stay unconditional.
- Voice build command passes the option `OFF`, uses clean `/usr/bin:/bin` build PATH, and never supplies a Miniconda nlohmann path.
- Daily launch is one repository command, backed by a non-secret JSON profile and stdlib-only preflight/launcher; it does not source or modify `/home/ning/voice_control_env.sh`.
- Dedicated runtime root is `${HOME}/model/lyz/voice_control_runtime`; its `.venv` and models are deployment state, never committed.
- Exact initial Python pins mirror the known working host dependency set; ARM64 absence of the pinned sherpa wheel is a stop condition, not permission to substitute or build from source.
- Routing change is limited to removing the outer Ollama-only gate; JSON schema, local parsers, topic names and publishing semantics remain unchanged.

## Scope IN
- `CMakeLists.txt`; voice scripts/config/tests; machine-readable voice dependency/profile/asset manifests; migration/context docs; `.ai/tasks`, `.ai/runs`, `.ai/reviews` created by the required workflow.
- Fixed current-host prefixes `/home/ning/model/lyz/voice_control_build`, `/home/ning/model/lyz/voice_control_install`, `/home/ning/model/lyz/voice_control_runtime`.
- Read-only inspection of generated build/install metadata and external model files, with no credentials recorded.

## Scope OUT (Must NOT have)
- Any modification to `src/robot_controller.cpp`, controller behavior, MoveIt configuration, ROS topic/message/schema, units, arm semantics or live motion path.
- Starting `robot_controller`, MoveIt, vendor drivers, greeting demo, or publishing action JSON on a live `/robot_command` topic.
- ESP-IDF, XiaoZhi firmware, MQTT/UDP/MCP/OTA code, whole-stack containers, new cloud services, secret/profile values in Git, or automatic `sudo` package installation.
- Editing `/home/ning/voice_control_env.sh`, Conda environments, credentials, private keys or existing environment files.

## Open questions
- None. Target wheel availability and model checks are executable stop gates with explicit failure behavior, not design questions.

## Approval gate
status: approved
approved-by-user: 2026-07-13 "批准计划"
official-plan: `.ai/plans/xiaozhi-inspired-voice-migration.md`
implementation-authorized: false

## Metis receipt
- session: `/root/migration_plan_metis`
- verdict: direction sound after mandatory corrections.
- folded corrections: classify CMake option as interim voice-only lane and defer package split; restore documented Dify-before-Ollama behavior as a bug fix; enforce venv plus ROS origins with user-site/Conda rejection; make prefixes profile-controlled; distinguish required/conditional/optional preflight; add opt-in fail-closed no-motion sink; require concrete asset version/hash/license data; specify six-case routing matrix; separate x86 proof from Jetson `待确认`; preserve prior runtime and controller ownership.
- contrarian challenge resolved: a ROS package split is cleaner but crosses controller ownership and migration scope, so it is explicitly deferred.

## High-accuracy review ledger
- Round 1 Momus: `/root/migration_plan_momus`, `REJECT`; fixed controller-default QA, sequential file ownership, Dify/profile paths, asset copy, no-motion lifecycle, bounded QA, command contract and host-path redaction.
- Round 1 independent CLI: session `019f5a49-e3c5-78d3-8925-030245836d7a`, `gpt-5.6-sol` with `xhigh`, `REJECT`; fixed reproducible baseline, exact schemas, ordering, service config, asset safety, CMake isolation, routing/clean-archive/commit/secret contracts.
- Round 2 Momus: `/root/migration_plan_momus_r2`, `REJECT`; fixed shared resolver/defaults, asset digest/path rules, isolated venv, exhaustive CLI exits, file ownership, greeting-first sink, bounded process-group QA, offline install arguments, detached rollback, literal base guard, existing-root sentinel scan and precise CMake assertions.
- Round 2 independent CLI: session `019f5a5e-e978-7762-8a72-14dd813b1dd7`, `gpt-5.6-sol` with `xhigh`, `REJECT`; fixed Git prerequisite and filtered archive, literal four-component manifest, wheel release/install separation, secret-free setup and final-process injection, TTS-safe singleton QA, accurate voice-first routing matrix, named migration files and non-destructive rollback evidence.
- Round 3: pending fresh Momus plus fresh independent CLI; both must return unconditional `OKAY` before planning completes.
<!-- When exploration is exhausted and unknowns are answered, set status: awaiting-approval. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->
