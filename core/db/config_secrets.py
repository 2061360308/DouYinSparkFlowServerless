"""Encrypted system credentials. Key name is authenticated to prevent swapping rows."""
import secrets
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from core.services import ValidationError

SECRET_KEYS = frozenset({'platform_access_key_id', 'platform_access_key_secret', 'image_registry_password'})


def _key() -> bytes:
    try:
        key = base64.b64decode(os.environ.get('SPARK_COOKIE_KEY_B64', ''), validate=True)
        if len(key) != 32:
            raise ValueError()
        return key
    except ValueError:
        raise ValidationError('保存系统凭据需要固定的 32 字节 SPARK_COOKIE_KEY_B64') from None


def encrypt(key: str, value: str) -> dict:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_key()).encrypt(
        nonce, value.encode(), ('system-config-v1:' + key).encode())
    return {'ciphertext': ciphertext, 'nonce': nonce}


def decrypt(row) -> str:
    try:
        return AESGCM(_key()).decrypt(
            row.nonce, row.ciphertext, ('system-config-v1:' + row.key).encode()).decode()
    except Exception:
        raise ValidationError('无法解密系统凭据，请恢复原 SPARK_COOKIE_KEY_B64 或重新填写凭据') from None
