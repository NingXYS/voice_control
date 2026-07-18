import os
import subprocess
import unittest


SYSTEM_PYTHON_COMMANDS = {
    "version": "PY_VERSION=$(env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I -c 'import sys; print(f\"{sys.version_info.major}.{sys.version_info.minor}\")')",
    "ensurepip": "if ! env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I -c 'import ensurepip' >/dev/null 2>&1; then",
    "venv": 'env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I -m venv --system-site-packages "$VENV_DIR"',
}
PIP_INSTALL_COMMAND = (
    'env -i HOME="$HOME" USER="$USER" '
    'PATH="${VENV_DIR}/bin:/usr/bin:/bin" PYTHONNOUSERSITE=1 '
    '"$VENV_DIR/bin/python" -I -m pip install --isolated --ignore-installed '
    '-r "${REPO_ROOT}/requirements/voice-wake.txt"'
)
POLLUTION_VARIABLES = (
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
    "CONDA_EXE",
    "PYTHONHOME",
    "PYTHONPATH",
    "LD_LIBRARY_PATH",
)
VENV_FIRST_PATH_COMMAND = 'export PATH="${VOICE_WAKE_VENV_DIR}/bin:/usr/bin:/bin"'
NO_USER_SITE_COMMAND = "export PYTHONNOUSERSITE=1"


def _shell_logical_commands(text: str) -> list[str]:
    commands: list[str] = []
    fragments: list[str] = []
    for physical_line in text.splitlines():
        stripped = physical_line.strip()
        if not stripped or stripped.startswith("#"):
            fragments = []
            continue
        continues = stripped.endswith("\\")
        fragments.append(stripped[:-1].rstrip() if continues else stripped)
        if not continues:
            commands.append(" ".join(" ".join(fragments).split()))
            fragments = []
    if fragments:
        commands.append(" ".join(" ".join(fragments).split()))
    return commands


def _has_all_system_python_commands(commands: list[str]) -> bool:
    return all(command in commands for command in SYSTEM_PYTHON_COMMANDS.values())


def _has_pip_install_command(commands: list[str]) -> bool:
    return PIP_INSTALL_COMMAND in commands


def _has_launcher_cleanup(commands: list[str]) -> bool:
    required = [
        *(f"unset {variable}" for variable in POLLUTION_VARIABLES),
        VENV_FIRST_PATH_COMMAND,
        NO_USER_SITE_COMMAND,
    ]
    return all(command in commands for command in required)

class VoiceWakeStartupTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.cmakelists_path = os.path.join(self.repo_root, "CMakeLists.txt")
        self.setup_script_path = os.path.join(self.repo_root, "scripts", "setup_voice_wake.sh")
        self.run_script_path = os.path.join(self.repo_root, "scripts", "run_voice_wake.sh")

    def test_cmakelists_structure(self):
        """Verify that CMakeLists.txt has the VOICE_CONTROL_BUILD_ROBOT_CONTROLLER option and wraps robot_controller targets."""
        self.assertTrue(os.path.exists(self.cmakelists_path), "CMakeLists.txt does not exist")
        with open(self.cmakelists_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 1. 声明 option(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER ... ON)
        self.assertIn("option(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER", content)
        # Check if option defaults to ON
        self.assertTrue(any(line.strip().startswith("option(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER") and "ON" in line for line in content.splitlines()), 
                        "VOICE_CONTROL_BUILD_ROBOT_CONTROLLER option should be ON by default")

        # 2. check that ament_cmake and Python install are outside the if-block (no condition wrapping them)
        # We can just verify their presence in the file generally, and verify they are not inside if(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER)
        self.assertIn("find_package(ament_cmake REQUIRED)", content)
        self.assertIn("install(PROGRAMS", content)
        self.assertIn("install(FILES", content)
        self.assertIn("ament_package()", content)

        # 3. controller specific packages and targets must be inside the if block
        # Let's verify that tf2, moveit etc are inside if(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER) ... endif()
        # We can parse blocks or check text containment. Let's do a simple check.
        # Check if find_package(moveit_ros_planning_interface REQUIRED) is inside the condition
        # We can do this by checking the lines between if(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER) and matching endif().
        if_index = content.find("if(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER)")
        self.assertNotEqual(if_index, -1, "if(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER) block not found")
        
        # Simple stack-based brace matching or similar for nested if/endif is not strictly needed if we don't have nested ones.
        # Let's count how many endif() or other statements are there. Or just verify the sub-strings are after the if and before its endif.
        # Find the first endif() after if(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER)
        endif_index = content.find("endif()", if_index)
        self.assertNotEqual(endif_index, -1, "endif() matching the option block not found")
        
        block_content = content[if_index:endif_index]
        self.assertIn("moveit_ros_planning_interface", block_content)
        self.assertIn("tf2", block_content)
        self.assertIn("nlohmann_json", block_content)
        self.assertIn("add_executable(robot_controller", block_content)
        self.assertIn("target_link_libraries(robot_controller", block_content)
        
        # Verify that these controller packages are NOT found outside this block (except maybe inside comments or the check itself)
        # Let's make sure the overall count in the file matches what is inside the block.
        outer_content = content[:if_index] + content[endif_index:]
        self.assertNotIn("add_executable(robot_controller", outer_content)
        self.assertNotIn("moveit_ros_planning_interface REQUIRED", outer_content)

    def test_shell_scripts_syntax(self):
        """Verify that shell scripts pass bash -n check."""
        for path in [self.setup_script_path, self.run_script_path]:
            self.assertTrue(os.path.exists(path), f"Script {path} does not exist")
            res = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Syntax check failed for {path}: {res.stderr}")

    def test_run_script_content(self):
        """Verify run_voice_wake.sh content constraints."""
        self.assertTrue(os.path.exists(self.run_script_path), "run_voice_wake.sh does not exist")
        with open(self.run_script_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("PYTHONNOUSERSITE=1", content, "run_voice_wake.sh must set PYTHONNOUSERSITE=1")
        self.assertNotIn("/tmp/voice_control_install13", content, "run_voice_wake.sh must not contain the temporary path /tmp/voice_control_install13")
        
        # Must clean conda and python env vars
        self.assertTrue("CONDA_PREFIX" in content, "run_voice_wake.sh should reference CONDA_PREFIX for cleaning")
        self.assertTrue("PYTHONPATH" in content, "run_voice_wake.sh should reference PYTHONPATH for cleaning")
        
        self.assertIn("ONLINE_INSTALL_ROOT", content)
        self.assertIn("install_online", content)
        self.assertIn("voice_control/lib/voice_control/voice_wake_entry.py", content)
        self.assertIn("TTS_MODEL_DIR", content)
        self.assertIn("DIFY_API_KEY", content)
        self.assertIn("sherpa-onnx-paraformer-zh-2023-09-14", content)
        self.assertIn('WAKE_DETECTOR_MODE:-kws', content)
        self.assertIn('cmp -s "${REPO_ROOT}/scripts/${file}"', content)
        self.assertIn("voice_audio_session.py", content)
        
        # Must only start voice_wake_entry.py (and not robot_controller)
        self.assertIn("voice_wake_entry.py", content)
        self.assertNotIn("robot_controller", content, "run_voice_wake.sh must not start or reference robot_controller")

    def test_setup_script_content(self):
        """Verify setup_voice_wake.sh content constraints."""
        self.assertTrue(os.path.exists(self.setup_script_path), "setup_voice_wake.sh does not exist")
        with open(self.setup_script_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("/usr/bin/python3", content, "setup_voice_wake.sh must explicitly use /usr/bin/python3")
        self.assertIn("-DVOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF", content, "setup_voice_wake.sh must pass -DVOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF")
        self.assertNotIn("sudo", content, "setup_voice_wake.sh must not contain sudo")
        
        self.assertIn("build_online", content)
        self.assertIn("install_online", content)
        self.assertIn("log_online", content)

        # Must pass PYTHONNOUSERSITE=1 to colcon build env -i subshell
        self.assertTrue("PYTHONNOUSERSITE=1" in content, "setup_voice_wake.sh clean build subshell must use/pass PYTHONNOUSERSITE=1")

    def test_setup_bootstraps_python_metadata_tools(self):
        with open(self.setup_script_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("pip>=23.2", content)
        self.assertIn("setuptools>=68,<80", content)
        self.assertIn("wheel", content)
        self.assertIn("packaging>=24.0", content)

    def test_setup_requires_self_contained_venv_pip(self):
        """Verify setup_voice_wake.sh does not contain --without-pip, uses system-site-packages, and uses strictly isolated pip install invocation."""
        self.assertTrue(os.path.exists(self.setup_script_path), "setup_voice_wake.sh does not exist")
        with open(self.setup_script_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("--without-pip", content, "setup_voice_wake.sh must not use --without-pip")
        self.assertIn("--system-site-packages", content, "setup_voice_wake.sh must use --system-site-packages")
        
        # Verify it has check for ensurepip
        self.assertIn("ensurepip", content, "setup_voice_wake.sh must preflight check ensurepip")

        commands = _shell_logical_commands(content)
        self.assertTrue(_has_pip_install_command(commands))

        mutations = {
            "missing-no-user-site": PIP_INSTALL_COMMAND.replace(" PYTHONNOUSERSITE=1", "", 1),
            "system-interpreter": PIP_INSTALL_COMMAND.replace('"$VENV_DIR/bin/python"', "/usr/bin/python3", 1),
            "missing-isolated": PIP_INSTALL_COMMAND.replace(" --isolated", "", 1),
            "wrong-requirements": PIP_INSTALL_COMMAND.replace("requirements/voice-wake.txt", "requirements.txt", 1),
        }
        for name, replacement in mutations.items():
            with self.subTest(mutation=name):
                mutated = [replacement if command == PIP_INSTALL_COMMAND else command for command in commands]
                self.assertFalse(_has_pip_install_command(mutated))

        for non_command in (f"# {PIP_INSTALL_COMMAND}", f"echo '{PIP_INSTALL_COMMAND}'"):
            with self.subTest(non_command=non_command[:20]):
                self.assertFalse(_has_pip_install_command(_shell_logical_commands(non_command)))

        # Verify validation of pip file path using readlink/realpath
        self.assertTrue("pip.__file__" in content, "setup_voice_wake.sh must validate pip location using pip.__file__")
        self.assertTrue("readlink" in content or "realpath" in content, "setup_voice_wake.sh must resolve pip.__file__ path to realpath")

    def test_setup_routes_colcon_logs_outside_repository(self):
        """Verify colcon build routes logs outside repository, using exact colcon --log-base "$VOICE_WAKE_RUNTIME_ROOT/log" build syntax."""
        self.assertTrue(os.path.exists(self.setup_script_path), "setup_voice_wake.sh does not exist")
        with open(self.setup_script_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('colcon --log-base "$LOG_DIR" build', content)

    def test_setup_isolates_all_system_python_invocations(self):
        """Verify version check, ensurepip check, and venv creation are isolated using env -i, PYTHONNOUSERSITE=1, and python -I."""
        self.assertTrue(os.path.exists(self.setup_script_path), "setup_voice_wake.sh does not exist")
        with open(self.setup_script_path, "r", encoding="utf-8") as f:
            content = f.read()

        commands = _shell_logical_commands(content)
        self.assertTrue(_has_all_system_python_commands(commands))

        removals = {
            "env-i": "env -i ",
            "no-user-site": "PYTHONNOUSERSITE=1 ",
            "isolated-python": "-I ",
        }
        for invocation, target in SYSTEM_PYTHON_COMMANDS.items():
            for isolation, token in removals.items():
                with self.subTest(invocation=invocation, isolation=isolation):
                    replacement = target.replace(token, "", 1)
                    mutated = [replacement if command == target else command for command in commands]
                    self.assertFalse(_has_all_system_python_commands(mutated))

    def test_shell_command_helper_rejects_non_commands_and_similar_names(self):
        target = "unset CONDA_PREFIX"
        attacks = (
            f"# {target}",
            f"echo '{target}'",
            "unset CONDA_PREFIX_EXTRA",
            "unset CONDA_PREFIX_BACKUP",
            "unset\nCONDA_PREFIX",
            "unset \\" + "\n# interruption\nCONDA_PREFIX",
            "unset \\" + "\n\nCONDA_PREFIX",
        )
        for text in attacks:
            with self.subTest(text=text):
                self.assertNotIn(target, _shell_logical_commands(text))

    def test_setup_rejects_similar_venv_prefix_for_pip(self):
        """Assert verification uses strict directory prefix boundaries for REAL_PIP_PATH and REAL_VENV_DIR."""
        self.assertTrue(os.path.exists(self.setup_script_path), "setup_voice_wake.sh does not exist")
        with open(self.setup_script_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Verify strict directory prefix boundaries check: either "in $REAL_VENV_DIR/*" or similar pattern
        # E.g. [[ "$REAL_PIP_PATH" != "$REAL_VENV_DIR"/* ]]
        self.assertTrue(
            '"$REAL_VENV_DIR"/*' in content or '"${REAL_VENV_DIR}"/*' in content,
            "setup_voice_wake.sh must use strict pattern matching with trailing /* to assert directory boundaries"
        )

        # Helper logic check to prove pattern matching rejects venv-evil/pip
        def check_path_match(venv, pip_path):
            cmd = f'REAL_VENV_DIR="{venv}"; REAL_PIP_PATH="{pip_path}"; if [[ "$REAL_PIP_PATH" == "$REAL_VENV_DIR"/* ]]; then echo "OK"; else echo "FAIL"; fi'
            res = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
            return res.stdout.strip()

        self.assertEqual(check_path_match("/tmp/runtime/.venv", "/tmp/runtime/.venv/lib/python3.10/site-packages/pip/__init__.py"), "OK")
        self.assertEqual(check_path_match("/tmp/runtime/.venv", "/tmp/runtime/.venv-evil/lib/python3.10/site-packages/pip/__init__.py"), "FAIL")

    def test_launcher_clears_every_declared_pollution_variable(self):
        """Verify run_voice_wake.sh unsets Conda, python, and LD_LIBRARY_PATH pollution variables using exact unset syntax, and sets PATH/PYTHONNOUSERSITE correctly."""
        self.assertTrue(os.path.exists(self.run_script_path), "run_voice_wake.sh does not exist")
        with open(self.run_script_path, "r", encoding="utf-8") as f:
            content = f.read()

        commands = _shell_logical_commands(content)
        self.assertTrue(_has_launcher_cleanup(commands))

        for variable in POLLUTION_VARIABLES:
            target = f"unset {variable}"
            for mutation, replacement in (
                ("assignment", f"{variable}=/tmp/still-polluted"),
                ("omission", None),
            ):
                with self.subTest(variable=variable, mutation=mutation):
                    mutated = [command for command in commands if command != target]
                    if replacement is not None:
                        mutated.append(replacement)
                    self.assertFalse(_has_launcher_cleanup(mutated))

        wrong_path = 'export PATH="/usr/bin:/bin:${VOICE_WAKE_VENV_DIR}/bin"'
        mutated_path = [wrong_path if command == VENV_FIRST_PATH_COMMAND else command for command in commands]
        self.assertFalse(_has_launcher_cleanup(mutated_path))

if __name__ == "__main__":
    unittest.main()
