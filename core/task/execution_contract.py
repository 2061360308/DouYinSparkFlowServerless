"""Shared fingerprint for the exact business data used to compose a message."""
import hashlib
import json


def message_fingerprint(spark: dict) -> str:
    values = [spark.get('account_id'), spark.get('target_name'), spark.get('target_sec_uid') or '',
              spark.get('message_template'), spark.get('send_time')]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()
