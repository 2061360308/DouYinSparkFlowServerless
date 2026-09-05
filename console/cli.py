"""控制台管理 CLI。

用法（需先建表：``python -m db``）：
    # 创建管理员（省略密码则自动生成并打印）
    DATABASE_URL=... python -m console create-admin <用户名> [--password <密码>]

仅依赖数据库与 Argon2，不需要加密密钥环境变量。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from tortoise import Tortoise, connections

from console.security import PasswordService
from console.services import Conflict, ValidationError
from console.services.users import UserService
from db.models import TORTOISE_ORM


async def _create_admin(username: str, password: str | None) -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        service = UserService(PasswordService())
        try:
            user, temporary = await service.create(username, password=password, role="admin")
        except (Conflict, ValidationError) as error:
            print(f"创建失败：{error}", file=sys.stderr)
            raise SystemExit(1) from error
        print(f"已创建管理员：{user.username}")
        print(f"初始密码：{temporary}")
        print("登录后请立即修改密码。")
    finally:
        await connections.close_all()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="console", description="DouyinSpark 控制台 CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="创建管理员账号")
    admin.add_argument("username")
    admin.add_argument("--password", default=None, help="不填则自动生成")
    args = parser.parse_args(argv)

    if args.command == "create-admin":
        asyncio.run(_create_admin(args.username, args.password))


if __name__ == "__main__":
    main()
