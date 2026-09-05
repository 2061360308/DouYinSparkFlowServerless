"""BrowserManager / Local & Cloud 后端逻辑测试（不启动真实 chrome、不访问真实 FC）。

用临时 SQLite 隔离 DB；本地后端 mock 掉进程相关函数，云端后端 mock 掉签名 HTTP /
FC OpenAPI。所有场景在单个事件循环内顺序执行，规避跨事件循环的锁绑定问题。
"""

import os
import shutil
import tempfile
import unittest

# 必须在导入 db 之前指定隔离用的临时数据库
_TMP_DB = "test_browser_tmp.sqlite3"
os.environ["DATABASE_URL"] = "sqlite://" + _TMP_DB

import browser.local as local_mod  # noqa: E402
from browser.manager import BrowserManager, is_docker_deployment  # noqa: E402
from browser.manager import ERR_AT_CAPACITY  # noqa: E402


# ---- 本地后端 mock：模拟浏览器进程注册表，无需真实 chrome ----
_STATE = {"next_pid": 1000, "alive": set()}


def _fake_launch(**kw):
    pid = _STATE["next_pid"]
    _STATE["next_pid"] += 1
    _STATE["alive"].add(pid)
    d = tempfile.mkdtemp(prefix="faketest-")
    return {
        "ok": True, "code": 0, "pid": pid, "port": 9222,
        "ws_url": f"ws://127.0.0.1:9222/devtools/browser/{pid}",
        "debug_host": "127.0.0.1", "user_data_dir": d, "log_path": d + "/c.log",
        "headless": True, "platform": "windows", "msg": "ok",
    }


def _fake_is_alive(pid):
    return pid in _STATE["alive"]


def _fake_cdp_ok(host, port, timeout=1.5):
    return True


def _fake_stop(pid, cleanup_dir=None, timeout=6.0):
    _STATE["alive"].discard(pid)
    if cleanup_dir:
        shutil.rmtree(cleanup_dir, ignore_errors=True)
    return {"ok": True, "code": 0, "pid": pid, "msg": "stopped", "detail": {}}


async def _clear_rows():
    from db import BrowserInstanceDB
    for r in await BrowserInstanceDB.list_all():
        await BrowserInstanceDB.delete(r["sessionid"])


async def _count():
    from db import BrowserInstanceDB
    return await BrowserInstanceDB.count()


class TestBrowserManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from db.init_db import init_db
        await init_db()
        await _clear_rows()

    async def asyncTearDown(self):
        await BrowserManager._reset_for_test()
        await _clear_rows()

    # ------------------------------------------------------------------
    async def test_local_backend_flow(self):
        os.environ["DouyinSparkDocker"] = "1"
        self.assertTrue(is_docker_deployment())

        orig = (local_mod.launch, local_mod.is_alive, local_mod._cdp_ok, local_mod.stop)
        local_mod.launch = _fake_launch
        local_mod.is_alive = _fake_is_alive
        local_mod._cdp_ok = _fake_cdp_ok
        local_mod.stop = _fake_stop
        try:
            await BrowserManager._reset_for_test()
            mgr = await BrowserManager.get_instance()
            await mgr.backend.stop_reaper()  # 避免后台回收干扰断言
            self.assertEqual(mgr.mode, "local")

            # 1) 新建
            r1 = await mgr.acquire("s1", seed="1", region="CN")
            self.assertTrue(r1["ok"], r1)
            self.assertEqual(r1["mode"], "local")
            self.assertTrue(r1["ws_url"].startswith("ws://"))
            self.assertEqual(r1["headers"], {})
            pid1 = r1["pid"]
            self.assertEqual(await _count(), 1)

            # 2) 复用（同 sessionid 不新建、pid 不变、不占额外名额）
            r1b = await mgr.acquire("s1")
            self.assertTrue(r1b["ok"])
            self.assertEqual(r1b["pid"], pid1)
            self.assertEqual(await _count(), 1)

            # 3) 并发上限：置为 1，另一个 sessionid 被拒
            mgr.concurrency = 1
            r2 = await mgr.acquire("s2", seed="2")
            self.assertFalse(r2["ok"])
            self.assertEqual(r2["code"], ERR_AT_CAPACITY)
            self.assertEqual(await _count(), 1)

            # 4) 销毁 s1 后可再申请 s2
            d1 = await mgr.destroy("s1")
            self.assertTrue(d1["ok"])
            self.assertEqual(await _count(), 0)
            self.assertNotIn(pid1, _STATE["alive"])  # 进程已被终止

            r2b = await mgr.acquire("s2", seed="2")
            self.assertTrue(r2b["ok"])
            self.assertEqual(await _count(), 1)

            # 5) get 命中 / 未命中
            g = await mgr.get("s2")
            self.assertIsNotNone(g)
            self.assertEqual(g["pid"], r2b["pid"])
            self.assertIsNone(await mgr.get("nope"))

            # 6) 失效自动重建：模拟进程死亡后再 acquire 应重启新进程
            _STATE["alive"].discard(r2b["pid"])
            r2c = await mgr.acquire("s2", seed="2")
            self.assertTrue(r2c["ok"])
            self.assertNotEqual(r2c["pid"], r2b["pid"])
            self.assertEqual(await _count(), 1)

            # 7) reaper 回收死亡进程
            _STATE["alive"].discard(r2c["pid"])
            await mgr.backend._reap_once()
            self.assertEqual(await _count(), 0)
        finally:
            local_mod.launch, local_mod.is_alive, local_mod._cdp_ok, local_mod.stop = orig
            os.environ.pop("DouyinSparkDocker", None)

    # ------------------------------------------------------------------
    async def test_cloud_backend_flow(self):
        os.environ.pop("DouyinSparkDocker", None)
        self.assertFalse(is_docker_deployment())

        from db.system_config_db import SystemConfigDB
        await SystemConfigDB.set_many({
            "fc_function_url": "https://fn-xyz.cn-hangzhou.fcapp.run",
            "function_name": "DYSparkCloakBrowser",
            "region": "cn-hangzhou",
            "target_account_id": "123456789",
            "platform_access_key_id": "AK",
            "platform_access_key_secret": "SK",
            "affinity_header_field_name": "sessionid",
            "fc_qualifier": "LATEST",
        })

        await BrowserManager._reset_for_test()
        mgr = await BrowserManager.get_instance()
        self.assertEqual(mgr.mode, "cloud")
        self.assertTrue(mgr.backend.configured)

        # mock 掉网络/OpenAPI：记录 /start 收到的配置头，控制可用性判定
        seen = {"start_calls": 0, "cfg_header": None, "deleted": []}
        usable = {"flag": False}

        def fake_start(fk, cfg_header):
            seen["start_calls"] += 1
            seen["cfg_header"] = cfg_header
            usable["flag"] = True  # /start 后即可用
            return {"status": "ready"}

        def fake_json_version_ok(fk):
            return usable["flag"]

        def fake_delete(fk):
            seen["deleted"].append(fk)
            usable["flag"] = False
            return True

        mgr.backend._start_sync = fake_start
        mgr.backend._json_version_ok = fake_json_version_ok
        mgr.backend._delete_session_safe = fake_delete

        import hashlib
        import base64
        import json

        # 1) 新建：签名 ws + 头齐全；X-Browser-Cfg 含 region->locale/timezone 归一
        r1 = await mgr.acquire("c1", seed="12345", region="CN")
        self.assertTrue(r1["ok"], r1)
        self.assertEqual(r1["mode"], "cloud")
        self.assertEqual(r1["pid"], 0)
        self.assertEqual(r1["ws_url"], "wss://fn-xyz.cn-hangzhou.fcapp.run/")
        self.assertEqual(seen["start_calls"], 1)
        fk1 = hashlib.sha256("c1".encode()).hexdigest()
        self.assertEqual(r1["fc_session_key"], fk1)
        # 握手签名头：亲和头 + Date + Authorization(FC AK:)
        self.assertEqual(r1["headers"]["sessionid"], fk1)
        self.assertIn("Date", r1["headers"])
        self.assertTrue(r1["headers"]["Authorization"].startswith("FC AK:"))
        cfg = json.loads(base64.urlsafe_b64decode(seen["cfg_header"]).decode())
        self.assertEqual(cfg["seed"], "12345")
        self.assertEqual(cfg["locale"], "zh-CN")
        self.assertEqual(cfg["timezone"], "Asia/Shanghai")
        self.assertEqual(await _count(), 1)

        # 2) 复用：/json/version 可用 → 不再调用 /start
        r1b = await mgr.acquire("c1")
        self.assertTrue(r1b["ok"])
        self.assertEqual(seen["start_calls"], 1)
        self.assertEqual(await _count(), 1)

        # 3) 并发上限拒绝
        mgr.concurrency = 1
        r2 = await mgr.acquire("c2", seed="2")
        self.assertFalse(r2["ok"])
        self.assertEqual(r2["code"], ERR_AT_CAPACITY)
        mgr.concurrency = 4

        # 4) 失效自动重建：/json/version 不可用 → 删会话 + 删库 → 重新 /start
        usable["flag"] = False
        r1c = await mgr.acquire("c1", seed="12345", region="CN")
        self.assertTrue(r1c["ok"])
        self.assertIn(fk1, seen["deleted"])   # 触发了 DeleteSession
        self.assertEqual(seen["start_calls"], 2)
        self.assertEqual(await _count(), 1)

        # 5) 销毁：调用 DeleteSession 且删库
        d = await mgr.destroy("c1")
        self.assertTrue(d["ok"])
        self.assertEqual(seen["deleted"].count(fk1), 2)
        self.assertEqual(await _count(), 0)

        # 6) get 未命中返回 None
        self.assertIsNone(await mgr.get("c1"))

    # ------------------------------------------------------------------
    async def test_cloud_not_configured(self):
        os.environ.pop("DouyinSparkDocker", None)
        from db.system_config_db import SystemConfigDB
        await SystemConfigDB.set_many({
            "fc_function_url": "", "function_name": "", "region": "cn-hangzhou",
            "platform_access_key_id": "", "platform_access_key_secret": "",
        })
        await BrowserManager._reset_for_test()
        mgr = await BrowserManager.get_instance()
        self.assertEqual(mgr.mode, "cloud")
        self.assertFalse(mgr.backend.configured)
        r = await mgr.acquire("x1")
        self.assertFalse(r["ok"])
        self.assertIn("未配置", r["msg"])


def tearDownModule():
    for suffix in ("", "-shm", "-wal"):
        try:
            os.remove(_TMP_DB + suffix)
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()
