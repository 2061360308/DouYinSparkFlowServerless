"""阿里云函数计算 FC HTTP 触发器请求签名（authType=function / AK 签名鉴权）。

当 HTTP 触发器以 ``authType="function"`` 创建时，公网 URL（``*.fcapp.run``）上的
每个请求都必须携带 AK 签名，否则返回 403。签名方案与阿里云 FC 官方一致
（HMAC-SHA256），与 OpenAPI 的 ROA/RPC 签名**不同**——OpenAPI（Get/DeleteSession
等）由 SDK 自动签名，本模块只负责“函数 URL”这一侧的签名。

    Authorization = "FC " + AccessKeyID + ":" + Signature
    Signature     = base64( HMAC-SHA256( AccessKeySecret, StringToSign ) )
    StringToSign  = HTTPMethod + "\n"
                  + Content-MD5 + "\n"
                  + Content-Type + "\n"
                  + Date + "\n"
                  + CanonicalizedFCHeaders
                  + CanonicalizedResource

- ``Date``：RFC1123 GMT（``email.utils.formatdate(usegmt=True)``）。服务端允许约
  ±15 分钟时钟偏移，因此签名头具时效性，重连时应重新签名。
- ``CanonicalizedFCHeaders``：所有以 ``x-fc-`` 开头的请求头，键转小写后按字典序排序，
  逐行 ``key:value\n``。（如使用 STS，需带 ``x-fc-security-token``，它会自动纳入签名。）
- ``CanonicalizedResource``：未转义的请求 path；若有 query，追加 ``"\n" + 排序后的
  ``k`` 或 ``k=v`` 列表。本项目端点（``/start`` /``/json/version`` / 根路径 ``/``）
  均无 query。
- 普通业务头（如 ``sessionID`` / ``X-Browser-Cfg``）**不**参与签名，可自由附加。

⚠️ 该方案依据阿里云各 FC SDK 通用签名实现；若后续官方文档细节调整（如是否要求
``x-fc-date``），以官方“HTTP 触发器请求签名”文档为准。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from email.utils import formatdate
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

__all__ = [
    "http_date",
    "content_md5",
    "string_to_sign",
    "signature",
    "sign_headers",
]


def http_date() -> str:
    """当前时间的 RFC1123 GMT 表示（用作 Date 头）。"""
    return formatdate(usegmt=True)


def content_md5(body: Optional[bytes]) -> str:
    """请求体的 Content-MD5（MD5 摘要的 base64）；无 body 返回空串。"""
    if not body:
        return ""
    return base64.b64encode(hashlib.md5(body).digest()).decode("ascii")


def _header(headers: Mapping[str, Any], name: str) -> str:
    """大小写不敏感地取头值；缺失返回空串。"""
    low = name.lower()
    for k, v in headers.items():
        if k.lower() == low:
            return "" if v is None else str(v)
    return ""


def _canonical_fc_headers(headers: Mapping[str, Any]) -> str:
    """以 x-fc- 开头的头：键转小写、按字典序排序，逐行 k:v\\n。"""
    fc: dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk.startswith("x-fc-"):
            fc[lk] = "" if v is None else str(v)
    return "".join(f"{k}:{fc[k]}\n" for k in sorted(fc))


def _canonical_resource(path: str, queries: Optional[Mapping[str, Any]]) -> str:
    """path（+ 规范化 query）。query 为空时仅返回 path。"""
    resource = path or "/"
    if not queries:
        return resource
    params: list[str] = []
    for key in queries:
        values = queries[key]
        if isinstance(values, (list, tuple)):
            for v in values:
                params.append(key if v is None else f"{key}={v}")
        elif values is None:
            params.append(key)
        else:
            params.append(f"{key}={values}")
    params.sort()
    return resource + "\n" + "\n".join(params)


def string_to_sign(
    method: str,
    path: str,
    headers: Mapping[str, Any],
    queries: Optional[Mapping[str, Any]] = None,
) -> str:
    """按 FC 规范拼接待签名字符串。"""
    return (
        f"{method.upper()}\n"
        f"{_header(headers, 'Content-MD5')}\n"
        f"{_header(headers, 'Content-Type')}\n"
        f"{_header(headers, 'Date')}\n"
        f"{_canonical_fc_headers(headers)}"
        f"{_canonical_resource(path, queries)}"
    )


def signature(
    access_key_secret: str,
    method: str,
    path: str,
    headers: Mapping[str, Any],
    queries: Optional[Mapping[str, Any]] = None,
) -> str:
    """计算 Base64(HMAC-SHA256(SK, StringToSign))。"""
    s = string_to_sign(method, path, headers, queries)
    digest = hmac.new(
        access_key_secret.encode("utf-8"), s.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def sign_headers(
    *,
    method: str,
    url: str,
    access_key_id: str,
    access_key_secret: str,
    extra_headers: Optional[Mapping[str, Any]] = None,
    security_token: Optional[str] = None,
    date: Optional[str] = None,
    body: Optional[bytes] = None,
    queries: Optional[Mapping[str, Any]] = None,
) -> dict:
    """为对函数 URL 的一次请求生成带签名的完整请求头。

    Args:
        method: HTTP 方法（GET/POST/...；WS 握手按 GET 签名）。
        url: 完整请求 URL（用于提取 path 参与签名）。
        access_key_id / access_key_secret: 平台账号 AK/SK。
        extra_headers: 附加业务头（如 sessionID、X-Browser-Cfg），不参与签名但会带上。
        security_token: STS 临时凭证 token（跨账号时用；单账号留空）。
        date: 覆盖 Date 头（默认取当前 GMT）；重签时应留空以取新鲜时间。
        body: 请求体（用于计算 Content-MD5；GET 无 body 留空）。
        queries: 查询参数（参与签名）。

    Returns:
        新的请求头 dict：extra_headers + Date(+Content-MD5/x-fc-security-token) +
        Authorization。
    """
    path = urlsplit(url).path or "/"
    headers: dict[str, Any] = dict(extra_headers or {})
    headers["Date"] = date or http_date()
    cmd5 = content_md5(body)
    if cmd5:
        headers["Content-MD5"] = cmd5
    if security_token:
        headers["x-fc-security-token"] = security_token
    sig = signature(access_key_secret, method, path, headers, queries)
    headers["Authorization"] = f"FC {access_key_id}:{sig}"
    return headers
