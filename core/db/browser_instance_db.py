"""browser_instance（浏览器实例管理）表的读写操作类。

并发设计说明（不依赖应用层锁）：

- create：直接单条 INSERT，不预查询。同 sessionid 的并发创建由数据库
  ``sessionid`` 主键唯一约束保证最多一个成功，其余抛出
  ``IntegrityError`` 并被转换为失败返回（SQLite 与 PostgreSQL 行为一致，
  且跨进程同样安全）。
- delete：单条 DELETE 天然原子且幂等，存在则删除、不存在删 0 行，
  均返回成功，无需先查。
- get：只读单条查询，无并发问题。
"""

from typing import Optional

from tortoise.exceptions import IntegrityError

from .models import BrowserInstance

from .connection import with_db

# 返回给调用方的状态码
OK = 0  # 操作成功
ERR_SESSION_EXISTS = 1001  # sessionid 已存在，创建失败
ERR_SESSION_NOT_FOUND = 1002  # sessionid 不存在，更新失败

# 业务返回结构统一为 {"ok": bool, "code": int, "detail": dict|None, "msg": str}
OK_MSG = "操作成功"


def _row_to_dict(row: BrowserInstance) -> dict:
    """将 BrowserInstance 记录转换为普通 dict（便于序列化/返回给调用方）。"""
    return {
        "sessionid": row.sessionid,
        "cfg": row.cfg,
        "create_at": row.create_at.isoformat(),
        "pid": row.pid,
    }


def _resp(ok: bool, code: int, detail: Optional[dict] = None, msg: str = OK_MSG) -> dict:
    """构造统一的业务返回结构。"""
    return {"ok": ok, "code": code, "detail": detail, "msg": msg}


class BrowserInstanceDB:
    """browser_instance（浏览器实例管理）表读写操作类（全部为静态方法，无需实例化）。"""

    @staticmethod
    @with_db
    async def create(sessionid: str, cfg: str, pid: int = 0) -> dict:
        """创建新的浏览器实例。

        直接依赖 ``sessionid`` 主键唯一约束：
        插入成功返回成功；已存在（含并发插入冲突）则返回失败与失败码，
        不会覆盖现有记录。

        返回: {"ok": bool, "code": int, "detail": dict|None, "msg": str}
        """
        try:
            row = await BrowserInstance.create(sessionid=sessionid, cfg=cfg, pid=pid)
        except IntegrityError:
            return _resp(False, ERR_SESSION_EXISTS, msg="sessionid 已存在")
        return _resp(True, OK, detail=_row_to_dict(row))

    @staticmethod
    @with_db
    async def get(sessionid: str) -> Optional[dict]:
        """获取浏览器实例详情；存在则返回具体信息，不存在返回 None。"""
        row = await BrowserInstance.get_or_none(sessionid=sessionid)
        return _row_to_dict(row) if row is not None else None

    @staticmethod
    @with_db
    async def delete(sessionid: str) -> dict:
        """删除浏览器实例（幂等）。

        单条 DELETE：存在则删除、不存在也无影响，均直接返回成功。

        返回: {"ok": bool, "code": int, "detail": None, "msg": str}
        """
        await BrowserInstance.filter(sessionid=sessionid).delete()
        return _resp(True, OK, msg="删除成功")

    @staticmethod
    @with_db
    async def update(
        sessionid: str,
        *,
        cfg: Optional[str] = None,
        pid: Optional[int] = None,
    ) -> dict:
        """更新已存在实例的 cfg / pid（用于刷新运行态，如 last_used、重启后回填 pid）。

        仅更新传入的非 None 字段；记录不存在时返回失败与失败码（不新建）。

        返回: {"ok": bool, "code": int, "detail": dict|None, "msg": str}
        """
        row = await BrowserInstance.get_or_none(sessionid=sessionid)
        if row is None:
            return _resp(False, ERR_SESSION_NOT_FOUND, msg="sessionid 不存在")
        fields: list[str] = []
        if cfg is not None:
            row.cfg = cfg
            fields.append("cfg")
        if pid is not None:
            row.pid = pid
            fields.append("pid")
        if fields:
            await row.save(update_fields=fields)
        return _resp(True, OK, detail=_row_to_dict(row))

    @staticmethod
    @with_db
    async def count() -> int:
        """当前受管浏览器实例总数（并发闸据此判断是否已达上限）。"""
        return await BrowserInstance.all().count()

    @staticmethod
    @with_db
    async def list_all() -> list[dict]:
        """列出全部实例（供本地 reaper 扫描超时/死亡实例、重启后重认领）。"""
        rows = await BrowserInstance.all()
        return [_row_to_dict(r) for r in rows]
