# Security Policy

## Credentials

Do not commit API keys, access tokens, private certificates, real `.env` files, speaker profiles, or other private runtime data.

Use environment variables or local files excluded by `.gitignore`. Example files may contain placeholders only.

If a credential is accidentally committed:

1. revoke or rotate it immediately;
2. remove it from the current branch;
3. review Git history and forks/caches as potentially exposed;
4. do not assume deleting the latest file invalidates the leaked secret.

## Robot execution

Voice and LLM output must not directly control robot hardware.

The intended execution boundary is:

```text
ASR / Local Intent / LLM
        ↓
strict command validation
        ↓
execution permission gate
        ↓
ROS 2 / external robot controller
        ↓
robot hardware
```

Real motion should remain disabled by default. The external robot controller is responsible for joint limits, workspace limits, collision checking, speed/force constraints, fault handling and physical emergency stop.

Speaker verification is an authorization aid only. It does not provide replay-attack resistance or functional safety.

## Vulnerability / safety reports

For credential exposure, unsafe command execution, command-validation bypasses, or robot-control issues, please open a minimal GitHub issue without including secrets, private recordings or sensitive deployment information.
