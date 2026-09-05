"""标准 5 段 cron 工具（无第三方依赖）。

字段：``minute hour day-of-month month day-of-week``
- 取值：minute 0-59, hour 0-23, dom 1-31, month 1-12(或 JAN-DEC), dow 0-7(0/7=周日, 或 SUN-SAT)
- 语法：``*`` / ``a`` / ``a-b`` / ``a-b/step`` / ``*/step`` / 逗号列表
- dom 与 dow 均被限定（非 ``*``）时，按 Vixie 语义「任一匹配即触发」。

提供：
- ``validate`` / ``matches`` / ``next_after``：调度核心（本地 Asia/Shanghai 语义）。
- ``to_six_field``：转阿里云 6 段（FC/EventBridge），处理 Quartz 的 ``?`` 约束。
- ``to_windows_xml``：生成 Windows 计划任务 XML（choice A：以 XML 表达调度）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Tuple
from xml.sax.saxutils import escape

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DOW_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}


class CronError(ValueError):
    """cron 表达式非法。"""


class CronConversionError(CronError):
    """cron 无法转换到目标平台（如 Windows/阿里云 的表达力限制）。"""


def _parse_field(field: str, lo: int, hi: int, names: dict | None = None) -> set:
    """把单个 cron 字段解析成命中的整数集合。"""
    result: set[int] = set()
    field = field.strip()
    if not field:
        raise CronError("cron 字段不能为空")
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise CronError("cron 字段包含空的逗号项")
        step = 1
        if "/" in part:
            base, _, step_s = part.partition("/")
            if not step_s.isdigit() or int(step_s) <= 0:
                raise CronError(f"非法步长：{part}")
            step = int(step_s)
            base = base.strip()
        else:
            base = part

        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            a, _, b = base.partition("-")
            start, end = _token(a, names, lo, hi), _token(b, names, lo, hi)
        else:
            start = _token(base, names, lo, hi)
            # "a/step" 语义为 a..hi 按 step；单值无步长则 end=start
            end = hi if step > 1 else start
        if start > end:
            raise CronError(f"区间下界大于上界：{part}")
        for v in range(start, end + 1, step):
            result.add(v)
    # dow 归一：7 视作 0（周日）
    if names is _DOW_NAMES and 7 in result:
        result.discard(7)
        result.add(0)
    for v in result:
        if v < lo or v > (hi if names is not _DOW_NAMES else 7):
            raise CronError(f"取值 {v} 超出范围 [{lo},{hi}]")
    return result


def _token(tok: str, names: dict | None, lo: int, hi: int) -> int:
    tok = tok.strip().lower()
    if names and tok in names:
        return names[tok]
    if not tok.lstrip("-").isdigit():
        raise CronError(f"非法取值：{tok}")
    return int(tok)


class _Cron:
    __slots__ = ("minute", "hour", "dom", "month", "dow", "dom_star", "dow_star")

    def __init__(self, expr: str):
        fields = expr.split()
        if len(fields) != 5:
            raise CronError(f"标准 cron 须为 5 段，实际 {len(fields)} 段：{expr!r}")
        m, h, dom, mon, dow = fields
        self.minute = _parse_field(m, 0, 59)
        self.hour = _parse_field(h, 0, 23)
        self.dom = _parse_field(dom, 1, 31)
        self.month = _parse_field(mon, 1, 12, _MONTH_NAMES)
        self.dow = _parse_field(dow, 0, 6, _DOW_NAMES)
        self.dom_star = dom.strip() == "*"
        self.dow_star = dow.strip() == "*"

    def matches(self, dt: datetime) -> bool:
        if dt.minute not in self.minute or dt.hour not in self.hour:
            return False
        if dt.month not in self.month:
            return False
        # Python weekday(): Mon=0..Sun=6 → cron dow: Sun=0..Sat=6
        cron_dow = (dt.weekday() + 1) % 7
        dom_ok = dt.day in self.dom
        dow_ok = cron_dow in self.dow
        if not self.dom_star and not self.dow_star:
            return dom_ok or dow_ok  # Vixie：两者均限定时取「或」
        if not self.dom_star:
            return dom_ok
        if not self.dow_star:
            return dow_ok
        return True  # 均为 * → 每天


# 搜索上界：闰年 2/29 的月度任务最坏约 4 年内必有匹配
_MAX_LOOKAHEAD_MIN = 366 * 24 * 60 * 4


def validate(expr: str) -> None:
    """校验 cron 合法，非法则抛 ``CronError``。"""
    _Cron(expr)


def matches(expr: str, dt: datetime) -> bool:
    """判断（Asia/Shanghai 语义的）时间 ``dt`` 是否命中 cron。"""
    return _Cron(expr).matches(dt)


def next_after(expr: str, after: datetime) -> datetime:
    """返回严格晚于 ``after`` 的下一个匹配时刻（分钟精度，本地语义）。"""
    cron = _Cron(expr)
    cursor = (after.replace(second=0, microsecond=0)) + timedelta(minutes=1)
    for _ in range(_MAX_LOOKAHEAD_MIN):
        if cron.matches(cursor):
            return cursor
        cursor += timedelta(minutes=1)
    raise CronConversionError(f"4 年内无匹配时刻，cron 可能无效：{expr!r}")


# ---------------------------------------------------------------------------
# 阿里云 6 段（FC / EventBridge，Quartz 风格：秒 分 时 日 月 周）
# ---------------------------------------------------------------------------
def _dow_std_to_quartz(dow: str) -> str:
    """标准 dow(0-6,0=SUN) → Quartz(1-7,1=SUN)，按 token 逐个平移。"""
    out_parts = []
    for part in dow.split(","):
        buf, num = "", ""

        def flush() -> None:
            nonlocal buf, num
            if num != "":
                buf += str((int(num) % 7) + 1)
                num = ""

        for ch in part:
            if ch.isdigit():
                num += ch
            else:
                flush()
                buf += ch
        flush()
        out_parts.append(buf)
    return ",".join(out_parts)


def to_six_field(expr: str) -> str:
    """标准 5 段 → 阿里云 6 段 cron（前置秒 0，处理 dom/dow 的 ``?`` 约束）。"""
    validate(expr)
    m, h, dom, mon, dow = expr.split()
    if dow.strip() == "*":
        dom_q, dow_q = dom, "?"          # 每天或按 dom：dow 置 ?
    elif dom.strip() == "*":
        dom_q, dow_q = "?", _dow_std_to_quartz(dow)
    else:
        raise CronConversionError(
            "阿里云(Quartz) cron 不支持同时限定 day-of-month 与 day-of-week"
        )
    return f"0 {m} {h} {dom_q} {mon} {dow_q}"


# ---------------------------------------------------------------------------
# Windows 计划任务 XML（schtasks /Create /XML 导入）
# ---------------------------------------------------------------------------
_WEEKDAY_TAGS = ["Sunday", "Monday", "Tuesday", "Wednesday",
                 "Thursday", "Friday", "Saturday"]
_MONTH_TAGS = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
_MAX_DISCRETE_TRIGGERS = 1000


def _iso_step_field(field: str) -> int | None:
    """字段形如 ``*`` 或 ``*/n`` 返回步长（分钟级重复），否则 None。"""
    field = field.strip()
    if field == "*":
        return 1
    if field.startswith("*/") and field[2:].isdigit() and int(field[2:]) > 0:
        return int(field[2:])
    return None


def to_windows_xml(
    expr: str, command: str, arguments: str, *, description: str = "", workdir: str = "",
) -> str:
    """生成 Windows 计划任务 XML（Task Scheduler 1.2）。

    覆盖常见形态；Task Scheduler 无法表达的组合抛 ``CronConversionError``：
    - 分钟为 ``*``/``*/n`` 且小时为 ``*`` 且不限定日期 → 单触发器 + 分钟级重复；
    - 其余枚举 (小时×分钟) 为离散 CalendarTrigger（上限 1000）；
    - 日期维度：按 dom → ScheduleByMonth；按 dow → ScheduleByWeek；否则 ScheduleByDay。
    """
    cron = _Cron(expr)
    m_field, h_field, dom_field, mon_field, dow_field = expr.split()
    triggers: List[str] = []

    minute_step = _iso_step_field(m_field)
    day_unrestricted = cron.dom_star and cron.dow_star and mon_field.strip() == "*"

    if minute_step is not None and h_field.strip() == "*" and day_unrestricted:
        # 每 n 分钟，全天、每天
        triggers.append(
            "<CalendarTrigger>"
            "<StartBoundary>2024-01-01T00:00:00</StartBoundary>"
            "<Enabled>true</Enabled>"
            "<Repetition>"
            f"<Interval>PT{minute_step}M</Interval>"
            "<Duration>P1D</Duration>"
            "<StopAtDurationEnd>true</StopAtDurationEnd>"
            "</Repetition>"
            "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
            "</CalendarTrigger>"
        )
    else:
        times: List[Tuple[int, int]] = [
            (h, mi) for h in sorted(cron.hour) for mi in sorted(cron.minute)
        ]
        if len(times) > _MAX_DISCRETE_TRIGGERS:
            raise CronConversionError(
                f"cron 展开出 {len(times)} 个触发点，超出 Windows 生成上限，"
                "请简化表达式（如用 */n 步长）"
            )
        day_block = _windows_day_block(cron, dom_field, mon_field, dow_field)
        for h, mi in times:
            triggers.append(
                "<CalendarTrigger>"
                f"<StartBoundary>2024-01-01T{h:02d}:{mi:02d}:00</StartBoundary>"
                "<Enabled>true</Enabled>"
                f"{day_block}"
                "</CalendarTrigger>"
            )

    return _WINDOWS_XML_TEMPLATE.format(
        description=escape(description or f"scheduled task ({expr})"),
        triggers="".join(triggers),
        command=escape(command),
        arguments=escape(arguments),
        workdir=(f"<WorkingDirectory>{escape(workdir)}</WorkingDirectory>" if workdir else ""),
    )


def _windows_day_block(cron: _Cron, dom_field: str, mon_field: str, dow_field: str) -> str:
    months = "" if mon_field.strip() == "*" else (
        "<Months>" + "".join(f"<{_MONTH_TAGS[m - 1]} />" for m in sorted(cron.month)) + "</Months>"
    )
    if not cron.dom_star and not cron.dow_star:
        raise CronConversionError(
            "Windows 计划任务无法同时按 day-of-month 与 day-of-week 触发，请二选一"
        )
    if not cron.dom_star:
        days = "".join(f"<Day>{d}</Day>" for d in sorted(cron.dom))
        return f"<ScheduleByMonth><DaysOfMonth>{days}</DaysOfMonth>{months}</ScheduleByMonth>"
    if not cron.dow_star:
        if months:
            raise CronConversionError(
                "Windows 计划任务的按周触发不支持叠加月份过滤，请去掉 month 限定"
            )
        days = "".join(f"<{_WEEKDAY_TAGS[d]} />" for d in sorted(cron.dow))
        return f"<ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek>{days}</DaysOfWeek></ScheduleByWeek>"
    if months:
        alldays = "".join(f"<Day>{d}</Day>" for d in range(1, 32))
        return f"<ScheduleByMonth><DaysOfMonth>{alldays}</DaysOfMonth>{months}</ScheduleByMonth>"
    return "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"


_WINDOWS_XML_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-16"?>'
    '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
    "<RegistrationInfo><Description>{description}</Description></RegistrationInfo>"
    "<Triggers>{triggers}</Triggers>"
    "<Settings>"
    "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
    "<StartWhenAvailable>true</StartWhenAvailable>"
    "<Enabled>true</Enabled>"
    "</Settings>"
    "<Actions>"
    "<Exec><Command>{command}</Command><Arguments>{arguments}</Arguments>{workdir}</Exec>"
    "</Actions>"
    "</Task>"
)
