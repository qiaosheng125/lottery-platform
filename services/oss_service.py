"""
阿里云 OSS 服务

提供预签名直传 URL 生成和对象删除功能。
"""

import os
from typing import Optional, Tuple
from datetime import datetime

from flask import current_app

try:
    import oss2
    OSS_AVAILABLE = True
except ImportError:
    OSS_AVAILABLE = False


def _get_bucket():
    if not OSS_AVAILABLE:
        raise RuntimeError('aliyun-oss2 not installed')

    auth = oss2.Auth(
        current_app.config['OSS_ACCESS_KEY_ID'],
        current_app.config['OSS_ACCESS_KEY_SECRET'],
    )
    bucket = oss2.Bucket(
        auth,
        current_app.config['OSS_ENDPOINT'],
        current_app.config['OSS_BUCKET_NAME'],
    )
    return bucket


def generate_presign_url(oss_key: str, expires: int = 300) -> Tuple[str, str]:
    """
    生成预签名上传 URL（PUT）。
    Returns: (presign_url, oss_key)
    """
    bucket = _get_bucket()
    url = bucket.sign_url('PUT', oss_key, expires, slash_safe=True)
    return url, oss_key


def build_oss_key(ticket_id: int, ext: str = 'jpg') -> str:
    """生成 OSS 对象 Key"""
    from datetime import datetime
    date_str = datetime.utcnow().strftime('%Y/%m/%d')
    return f"winning/{date_str}/{ticket_id}.{ext}"


def get_public_url(oss_key: str) -> str:
    """获取对象公开访问 URL"""
    domain = current_app.config.get('OSS_DOMAIN', '')
    if domain:
        return f"{domain.rstrip('/')}/{oss_key}"
    bucket_name = current_app.config.get('OSS_BUCKET_NAME', '')
    endpoint = current_app.config.get('OSS_ENDPOINT', '')
    return f"https://{bucket_name}.{endpoint}/{oss_key}"


def delete_object(oss_key: str) -> bool:
    """删除 OSS 对象（覆盖上传前调用）"""
    try:
        bucket = _get_bucket()
        bucket.delete_object(oss_key)
        return True
    except Exception as e:
        current_app.logger.warning(f"OSS delete {oss_key} failed: {e}")
        return False
