"""Batch config writes must roll back together on a real database failure."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class TestSystemConfigAtomic(unittest.TestCase):
    def test_failed_batch_rolls_back_and_valid_batch_commits(self):
        # A separate process isolates Tortoise configuration from other tests.
        script = '''
import asyncio
from tortoise import connections
from core.db.connection import open_persistent, close_persistent
from core.db.init_db import init_db
from core.db.system_config_db import SystemConfigDB

async def main():
    await init_db()
    await open_persistent()
    try:
        conn = connections.get('default')
        await conn.execute_script("""
            CREATE TRIGGER reject_test_region BEFORE UPDATE ON system_config
            WHEN NEW.config_key = 'region' AND NEW.config_value = 'fail'
            BEGIN SELECT RAISE(ABORT, 'injected database failure'); END;
        """)
        try:
            await SystemConfigDB.set_many({'browser_concurrency': 9, 'region': 'fail'})
        except Exception:
            pass
        else:
            raise AssertionError('Expected database write failure')
        actual = await SystemConfigDB.get_many(['browser_concurrency', 'region'])
        assert actual == {'browser_concurrency': '4', 'region': 'cn-hangzhou'}, actual
        await SystemConfigDB.set_many({'browser_concurrency': 8, 'region': 'cn-shanghai'})
        assert await SystemConfigDB.get_value('browser_concurrency') == '8'
        assert await SystemConfigDB.get_value('region') == 'cn-shanghai'
        try:
            await SystemConfigDB.set_many({'browser_concurrency': 7, 'unknown_key': 'x'})
        except ValueError:
            pass
        else:
            raise AssertionError('Unknown key accepted')
        assert await SystemConfigDB.get_value('browser_concurrency') == '8'
    finally:
        await close_persistent()
asyncio.run(main())
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, DATABASE_URL='sqlite://' + (Path(directory) / 'config.sqlite3').as_posix(), PYTHONUTF8='1')
            result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
