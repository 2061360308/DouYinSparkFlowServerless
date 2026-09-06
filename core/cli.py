"""控制台管理 CLI。

用法（需先建表：``python -m core.db``）：
    # 创建管理员（省略密码则自动生成并打印）
    python -m core create-admin <用户名> [--password <密码>]
    # 管理员已存在但忘记密码：重置(并确保为管理员)
    python -m core create-admin <用户名> --password <新密码> --reset
    # 重置任意已存在用户的密码(忘记密码自救; 省略 --password 则随机生成并打印)
    python -m core set-password <用户名> [--password <新密码>]

密码规则：至少 12 位。提供了 --password 时重置后可直接用新密码登录；
未提供则随机生成并要求下次登录改密。重置会使该用户已有会话失效。
仅依赖数据库与 Argon2，不需要加密密钥环境变量。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from tortoise import Tortoise, connections

from core.security import PasswordService
from core.services import Conflict, ValidationError
from core.services.users import UserService
from core.db.config import TORTOISE_ORM
from core.db.models import User, WebSession


async def _create_admin(username: str, password: str | None, reset: bool) -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        service = UserService(PasswordService())
        try:
            user, temporary = await service.create(username, password=password, role="admin")
        except Conflict:
            if not reset:
                print(
                    f"用户名已存在：{username}\n"
                    f"如需重置该管理员密码，请加 --reset，或用："
                    f"python -m core set-password {username} --password <新密码>",
                    file=sys.stderr,
                )
                raise SystemExit(1) from None
            await _apply_password(username, password, make_admin=True)
            return
        except ValidationError as error:
            print(f"创建失败：{error}", file=sys.stderr)
            raise SystemExit(1) from error
        print(f"已创建管理员：{user.username}")
        print(f"初始密码：{temporary}")
        print("登录后请立即修改密码。")
    finally:
        await connections.close_all()


async def _set_password(username: str, password: str | None) -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        await _apply_password(username, password, make_admin=False)
    finally:
        await connections.close_all()


async def _apply_password(username: str, password: str | None, *, make_admin: bool) -> None:
    """重置已存在用户的密码；连接需已初始化。"""
    name = username.strip().lower()
    user = await User.get_or_none(username=name)
    if user is None:
        print(f"用户不存在：{username}", file=sys.stderr)
        raise SystemExit(1)

    passwords = PasswordService()
    provided = password is not None
    new_password = password or UserService.temporary_password()
    try:
        user.password_hash = passwords.hash(new_password)
    except ValueError:
        print("密码至少需要 12 位。", file=sys.stderr)
        raise SystemExit(1) from None

    # 提供了明文密码 → 可直接登录；随机生成 → 要求下次改密
    user.must_change_password = not provided
    user.status = "active"
    user.failed_login_count = 0
    user.locked_until = None
    if make_admin:
        user.role = "admin"
    await user.save()
    # 使旧会话失效, 强制用新密码重新登录
    await WebSession.filter(user_id=user.id).delete()

    role_note = "（已设为管理员）" if make_admin and user.role == "admin" else ""
    print(f"已重置用户密码：{user.username}{role_note}")
    if provided:
        print("可用新密码直接登录。")
    else:
        print(f"临时密码：{new_password}")
        print("登录后需立即修改密码。")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="console", description="DouyinSpark 控制台 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="创建管理员账号(可 --reset 重置已存在管理员)")
    admin.add_argument("username")
    admin.add_argument("--password", default=None, help="不填则自动生成")
    admin.add_argument("--reset", action="store_true", help="用户名已存在时重置其密码并确保为管理员")

    setpwd = sub.add_parser("set-password", help="重置已存在用户的密码(忘记密码自救)")
    setpwd.add_argument("username")
    setpwd.add_argument("--password", default=None, help="不填则随机生成并打印")

    args = parser.parse_args(argv)

    if args.command == "create-admin":
        asyncio.run(_create_admin(args.username, args.password, args.reset))
    elif args.command == "set-password":
        asyncio.run(_set_password(args.username, args.password))


if __name__ == "__main__":
    main()
