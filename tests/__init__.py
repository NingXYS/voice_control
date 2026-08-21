import os

# Keep unit tests from inheriting a leftover motion cooldown between cases.
os.environ.setdefault("VOICE_MOTION_COOLDOWN_SEC", "0")
