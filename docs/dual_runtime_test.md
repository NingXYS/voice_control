# Offline and Online Voice Runtime Test

## Offline runtime

Use the existing Ollama based workspace separately.

## Online Dify runtime

Use a separate workspace and source only its ROS install environment.

Example:

```bash
cd ~/voice_control_online
colcon build
source install/setup.bash
```

Do not source offline and online installs in the same shell.

## Validation order

1. Wake word
2. VAD recording
3. Local ASR
4. Dify response
5. Local TTS
6. Robot command validation
7. robot_command publishing

The robot controller source is unchanged. The voice layer only publishes the existing command format.
