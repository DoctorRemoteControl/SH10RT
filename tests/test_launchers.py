"""Launcher checks: no implicit writes, no shell interpolation, safe setup failure."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import launch_sh10rt as launcher


class LauncherTests(unittest.TestCase):
    def test_terminal_arguments_are_forwarded_once_without_shell(self):
        arguments = ["start", "--host", "192.168.1.100", "--transport", "modbus",
                     "--serial", "TEST with spaces;$literal", "--execute", "--wait", "30"]
        with patch.object(launcher.subprocess, "run", return_value=Mock(returncode=5)) as run:
            self.assertEqual(launcher.run_tool(arguments), 5)
        run.assert_called_once_with([sys.executable, str(launcher.TOOL), *arguments])

    def test_preview_does_not_gain_execute_flag(self):
        arguments = ["start", "--host", "192.168.1.100", "--transport", "modbus", "--serial", "TEST000001"]
        with patch.object(launcher.subprocess, "run", return_value=Mock(returncode=0)) as run:
            self.assertEqual(launcher.run_tool(arguments), 0)
        self.assertNotIn("--execute", run.call_args.args[0])

    def test_help_and_invalid_input_do_not_install_or_connect(self):
        for arguments, code in ((["status", "--transport", "winet", "--help"], 0),
                                (["status", "--transport", "winet", "--host", "invalid"], 2)):
            with patch.object(launcher, "winet_python") as setup, \
                    patch.object(launcher.subprocess, "run") as run, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    launcher.run_tool(arguments)
                self.assertEqual(error.exception.code, code)
            setup.assert_not_called()
            run.assert_not_called()

    def test_setup_failure_does_not_run_tool(self):
        with patch.object(launcher, "winet_python", return_value=None), \
                patch.object(launcher.subprocess, "run") as run:
            self.assertEqual(launcher.run_tool(["status", "--host", "192.168.1.100", "--transport", "winet"]), 2)
        run.assert_not_called()

    def test_missing_venv_support_is_reported(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(launcher, "ENVIRONMENT", Path(directory) / "new environment"), \
                patch.object(launcher.importlib.util, "find_spec", return_value=None), \
                patch.object(launcher.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "venv")) as run, \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertIsNone(launcher.winet_python())
        self.assertEqual(run.call_count, 1)
        self.assertIn("Scan and Modbus still work", errors.getvalue())

    def test_menu_preview_remains_read_only_with_nondefault_unit(self):
        answers = ["3", "192.168.1.100", "modbus", "2", "TEST000001", "0"]
        with patch("builtins.input", side_effect=answers), \
                patch.object(launcher, "run_tool", return_value=0) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.menu(), 0)
        run.assert_called_once_with(["start", "--host", "192.168.1.100", "--transport", "modbus",
                                     "--unit", "2", "--serial", "TEST000001"])

    @unittest.skipUnless(os.name == "posix", "POSIX shell launcher smoke test")
    def test_shell_launchers_work_from_another_directory_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="sh10rt launcher ") as directory:
            root = Path(directory) / "project with spaces"
            (root / "scripts").mkdir(parents=True)
            for name in ("sh10rt.sh", "sh10rt.command", "scripts/launch_sh10rt.py", "scripts/sh10rt_lan.py"):
                shutil.copy2(launcher.ROOT / name, root / name)
            for name in ("sh10rt.sh", "sh10rt.command"):
                result = subprocess.run([str(root / name), "--help"], cwd="/", capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("scan,status,start,values", result.stdout)
                self.assertFalse((root / ".launcher-venv").exists())


if __name__ == "__main__":
    unittest.main()
