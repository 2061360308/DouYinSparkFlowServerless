"""Called inside the isolated API fixture; never uses real credentials."""
import base64
import os

from core.db.system_config_db import SystemConfigDB
from core.db.models.system import SystemConfig, SystemSecret
from core.db.config_secrets import SECRET_KEYS
from core.services import ValidationError


def check_config_secrets(client, csrf):
    endpoint = '/api/admin/system-config'
    key = 'platform_access_key_secret'
    fixture = 'legacy-fixture-secret'

    async def seed_legacy():
        await SystemConfig.filter(config_key=key).update(config_value=fixture)
    client.portal.call(seed_legacy)
    public = client.get(endpoint)
    assert fixture not in public.text and public.json()['secret_configured'][key]
    client.portal.call(SystemConfigDB.migrate_secrets)
    client.portal.call(SystemConfigDB.migrate_secrets)

    async def verify():
        assert (await SystemConfig.get(config_key=key)).config_value == ''
        row = await SystemSecret.get(key=key)
        assert fixture.encode() not in bytes(row.ciphertext)
        assert await SystemConfigDB.get_value(key) == fixture
    client.portal.call(verify)
    assert client.put(endpoint, json={'values': {key: ''}}).status_code == 403
    assert client.put(endpoint, json={'values': {key: ''}}, headers=csrf).status_code == 200
    assert client.portal.call(SystemConfigDB.get_value, key) == fixture
    replacement = 'replacement-fixture-secret'
    assert client.put(endpoint, json={'values': {key: replacement}}, headers=csrf).status_code == 200
    assert client.portal.call(SystemConfigDB.get_value, key) == replacement
    assert replacement not in client.get(endpoint).text
    conflict = client.put(endpoint, json={'values': {key: 'bad'}, 'clear_secret_keys': [key]}, headers=csrf)
    assert conflict.status_code == 400
    assert client.portal.call(SystemConfigDB.get_value, key) == replacement

    # Wrong encryption key must fail closed; redacted settings remain readable for repair.
    original = os.environ['SPARK_COOKIE_KEY_B64']
    os.environ['SPARK_COOKIE_KEY_B64'] = base64.b64encode(b'x' * 32).decode()
    try:
        try:
            client.portal.call(SystemConfigDB.get_value, key)
        except ValidationError:
            pass
        else:
            raise AssertionError('Wrong key accepted')
        assert client.get(endpoint).status_code == 200
    finally:
        os.environ['SPARK_COOKIE_KEY_B64'] = original

    assert client.put(endpoint, json={'values': {}, 'clear_secret_keys': ['region']}, headers=csrf).status_code == 400
    assert client.put(endpoint, json={'values': {}, 'clear_secret_keys': [key]}, headers=csrf).status_code == 200
    assert client.portal.call(SystemConfigDB.get_value, key) == ''
    assert not client.get(endpoint).json()['secret_configured'][key]
    # Exercise every secret through the bulk writer and verify no plaintext column remains.
    client.portal.call(SystemConfigDB.set_many, {k: 'bulk-fixture' for k in SECRET_KEYS})
    async def verify_bulk():
        assert all(not row.config_value for row in await SystemConfig.filter(config_key__in=list(SECRET_KEYS)))
        assert all(v == 'bulk-fixture' for v in (await SystemConfigDB.get_many(list(SECRET_KEYS))).values())
    client.portal.call(verify_bulk)
    assert client.put(endpoint, json={'values': {}, 'clear_secret_keys': list(SECRET_KEYS)}, headers=csrf).status_code == 200
    print('System secrets: migration, redaction, preservation, replacement, clear and wrong-key rejection PASS')
