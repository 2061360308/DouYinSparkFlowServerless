"""Run installation API checks in an isolated process/database."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class TestInstallAPI(unittest.TestCase):
    def test_installation_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, DATABASE_URL='sqlite://' + (Path(directory) / 'install.sqlite3').as_posix(), PYTHONUTF8='1')
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name('install_api_scenario.py'))],
                cwd=Path(__file__).resolve().parents[1], env=env,
                capture_output=True, text=True, encoding='utf-8', timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
