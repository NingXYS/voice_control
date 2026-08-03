cd /mnt/ssd/lyz
colcon build
source install/setup.bash
ros2 launch tianlian demo.launch.py






pkill -9 -f voice_wake_entry.py 2>/dev/null
pkill -9 -f gemini_detector 2>/dev/null

cd /mnt/ssd/voice_online
source .venv_online/bin/activate
source voice_control_online.env
export VOICE_ENABLE_ROBOT_COMMAND=1

.venv_online/bin/python -u scripts/voice_wake_entry.py
