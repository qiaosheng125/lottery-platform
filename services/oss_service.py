"""
图片存储服务

OSS 可用时使用阿里云 OSS；否则降级为本地 uploads/images/ 目录存储。
"""

import os
import uuid
from typing import Tuple
from datetime import datetime

from flask import current_app, url_for

try:
    import oss2
    OSS_AVAILABLE = True
except ImportError:
    OSS_AVAILABLE = False


def _oss_configured() -> bool:
    return (
        OSS_AVAILABLE
        and bool(current_app.config.get('OSS_ACCESS_KEY_ID'))
        and bool(current_app.config.get('OSS_ACCESS_KEY_SECRET'))
        and bool(current_app.config.get('OSS_BUCKET_NAME'))
    )


def _get_bucket():
    auth = oss2.Auth(
        current_app.config['OSS_ACCESS_KEY_ID'],
        current_app.config['OSS_ACCESS_KEY_SECRET'],
    )
    return oss2.Bucket(
        auth,
        current_app.config['OSS_ENDPOINT'],
        current_app.config['OSS_BUCKET_NAME'],
    )


def build_oss_key(ticket_id: int, ext: str = 'jpg') -> str:
    date_str = datetime.utcnow().strftime('%Y/%m/%d')
    return f"winning/{date_str}/{ticket_id}.{ext}"


def generate_presign_url(oss_key: str, expires: int = 300) -> Tuple[str, str]:
    """
    生成上传 URL。
    OSS 可用 → 返回预签名 PUT URL；
    否则 → 返回本地上传接口 URL（POST multipart）。
    """
    if _oss_configured():
        bucket = _get_bucket()
        url = bucket.sign_url('PUT', oss_key, expires, slash_safe=True)
        return url, oss_key

    # 本地模式：返回本地上传接口，oss_key 作为文件名标识
    local_key = oss_key.replace('/', '_')
    upload_url = f"/api/winning/upload-local?key={local_key}"
    return upload_url, local_key


def get_public_url(oss_key: str) -> str:
    if _oss_configured():
        domain = current_app.config.get('OSS_DOMAIN', '')
        if domain:
            return f"{domain.rstrip('/')}/{oss_key}"
        bucket_name = current_app.config.get('OSS_BUCKET_NAME', '')
        endpoint = current_app.config.get('OSS_ENDPOINT', '')
        return f"https://{bucket_name}.{endpoint}/{oss_key}"

    # 本地模式：返回静态文件 URL
    filename = oss_key if '/' not in oss_key else oss_key.replace('/', '_')
    return f"/uploads/images/{filename}"


def delete_object(oss_key: str) -> bool:
    if _oss_configured():
        try:
            _get_bucket().delete_object(oss_key)
            return True
        except Exception as e:
            current_app.logger.warning(f"OSS delete {oss_key} failed: {e}")
            return False

    # 本地模式：删除本地文件
    try:
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        path = os.path.join(upload_folder, 'images', oss_key)
        if os.path.exists(path):
            os.remove(path)
        return True
    except Exception:
        return False


def delete_stored_image(image_oss_key: str = None, image_url: str = None) -> bool:
    if image_oss_key:
        return delete_object(image_oss_key)

    if image_url and image_url.startswith('/uploads/images/'):
        try:
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
            filename = image_url.rsplit('/', 1)[-1]
            path = os.path.join(upload_folder, 'images', filename)
            if os.path.exists(path):
                os.remove(path)
            return True
        except Exception:
            return False

    return False
