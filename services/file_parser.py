"""
文件解析服务

处理 TXT 文件上传：解析文件名、解析每行内容、批量入库、推入 Redis 队列。
"""

import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy import text

from extensions import db
from models.file import UploadedFile
from models.ticket import LotteryTicket
from models.audit import AuditLog
from utils.filename_parser import parse_filename
from utils.amount_parser import calculate_ticket_amount
from utils.time_utils import beijing_now


def _generate_display_id() -> str:
    """生成文件展示ID，格式: YYYY/MM/DD-NN"""
    now = beijing_now()
    date_str = now.strftime('%Y/%m/%d')
    # 找今日12点之后的文件数量
    if now.hour < 12:
        cutoff = now.replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        cutoff = now.replace(hour=12, minute=0, second=0, microsecond=0)
    count = UploadedFile.query.filter(UploadedFile.uploaded_at >= cutoff).count()
    return f"{date_str}-{count + 1:02d}"


def process_uploaded_file(file_storage, uploader_id: int) -> dict:
    """
    处理单个上传的文件：
    1. 保存到磁盘
    2. 解析文件名
    3. 逐行解析内容并批量入库
    4. 推入 Redis 队列
    5. 记录审计日志

    Returns:
        {'success': bool, 'file_id': int, 'message': str, 'ticket_count': int}
    """
    from extensions import redis_client
    from services.notify_service import notify_all

    filename = file_storage.filename
    upload_folder = current_app.config['UPLOAD_FOLDER']
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    unique_id = uuid.uuid4().hex[:8]
    stored_filename = f"{timestamp}_{unique_id}_{filename}"
    file_path = os.path.join(upload_folder, stored_filename)
    file_storage.save(file_path)

    upload_dt = beijing_now()

    # Parse filename
    parsed_meta = parse_filename(filename, upload_dt)
    if not parsed_meta:
        os.remove(file_path)
        return {'success': False, 'message': f'文件名格式不正确: {filename}', 'file_id': None}

    # Create UploadedFile record
    uploaded_file = UploadedFile(
        display_id=_generate_display_id(),
        original_filename=filename,
        stored_filename=stored_filename,
        identifier=parsed_meta['identifier'],
        internal_code=parsed_meta['internal_code'],
        lottery_type=parsed_meta['lottery_type'],
        multiplier=parsed_meta['multiplier'],
        declared_amount=Decimal(str(parsed_meta['declared_amount'])),
        declared_count=parsed_meta['declared_count'],
        deadline_time=parsed_meta['deadline_time'],
        detail_period=parsed_meta['detail_period'],
        status='active',
        uploaded_by=uploader_id,
        uploaded_at=upload_dt,
    )
    db.session.add(uploaded_file)
    db.session.flush()  # get ID before bulk insert

    # Parse lines and bulk insert tickets
    tickets = []
    total_amount = Decimal('0')

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        with open(file_path, 'r', encoding='gbk') as f:
            lines = f.readlines()

    ticket_ids = []
    for line_no, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue

        amount = calculate_ticket_amount(line) or Decimal('0')
        total_amount += amount

        ticket = LotteryTicket(
            source_file_id=uploaded_file.id,
            line_number=line_no,
            raw_content=line,
            lottery_type=parsed_meta['lottery_type'],
            multiplier=parsed_meta['multiplier'],
            deadline_time=parsed_meta['deadline_time'],
            detail_period=parsed_meta['detail_period'],
            ticket_amount=amount,
            status='pending',
            admin_upload_time=upload_dt,
        )
        tickets.append(ticket)

    if not tickets:
        db.session.rollback()
        os.remove(file_path)
        return {'success': False, 'message': '文件内容为空', 'file_id': None}

    db.session.bulk_save_objects(tickets, return_defaults=True)

    # Update file counters
    uploaded_file.total_tickets = len(tickets)
    uploaded_file.pending_count = len(tickets)
    uploaded_file.actual_total_amount = total_amount

    db.session.flush()

    # Get ticket IDs for Redis
    ticket_objs = LotteryTicket.query.filter_by(
        source_file_id=uploaded_file.id, status='pending'
    ).with_entities(LotteryTicket.id).all()
    ticket_ids = [str(t.id) for t in ticket_objs]

    AuditLog.log(
        action_type='file_upload',
        user_id=uploader_id,
        resource_type='uploaded_file',
        resource_id=uploaded_file.id,
        details={'filename': filename, 'ticket_count': len(tickets)},
    )

    db.session.commit()

    # Push to Redis queue (after DB commit for consistency)
    if ticket_ids and redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.rpush('pool:pending', *ticket_ids)
            pipe.execute()
        except Exception as e:
            current_app.logger.warning(f"Redis push failed for file {uploaded_file.id}: {e}")

    # Notify via WebSocket
    try:
        notify_all('file_uploaded', {
            'lottery_type': parsed_meta['lottery_type'],
            'count': len(tickets),
            'deadline': parsed_meta['deadline_time'].isoformat() if parsed_meta['deadline_time'] else None,
            'file_id': uploaded_file.id,
        })
    except Exception:
        pass

    return {
        'success': True,
        'file_id': uploaded_file.id,
        'message': f'成功上传 {len(tickets)} 条数据',
        'ticket_count': len(tickets),
    }


def revoke_file(file_id: int, admin_id: int) -> dict:
    """撤回文件：将文件及所有 pending/assigned 票标记为 revoked"""
    from extensions import redis_client
    from services.notify_service import notify_all

    uploaded_file = UploadedFile.query.get(file_id)
    if not uploaded_file:
        return {'success': False, 'message': '文件不存在'}
    if uploaded_file.status == 'revoked':
        return {'success': False, 'message': '文件已撤回'}

    now = beijing_now()
    uploaded_file.status = 'revoked'
    uploaded_file.revoked_at = now
    uploaded_file.revoked_by = admin_id

    # Bulk update tickets
    revoked_count = LotteryTicket.query.filter(
        LotteryTicket.source_file_id == file_id,
        LotteryTicket.status.in_(['pending', 'assigned'])
    ).update({'status': 'revoked'}, synchronize_session=False)

    completed_count = LotteryTicket.query.filter_by(
        source_file_id=file_id, status='completed'
    ).count()

    # Update counters
    uploaded_file.pending_count = 0
    uploaded_file.assigned_count = 0

    AuditLog.log(
        action_type='file_revoke',
        user_id=admin_id,
        resource_type='uploaded_file',
        resource_id=file_id,
        details={'revoked_tickets': revoked_count, 'completed_tickets': completed_count},
    )
    db.session.commit()

    # Clean Redis (best effort)
    if redis_client:
        try:
            # Remove revoked ticket IDs from pending pool
            ticket_ids = LotteryTicket.query.filter_by(
                source_file_id=file_id
            ).with_entities(LotteryTicket.id).all()
            pipe = redis_client.pipeline()
            for (tid,) in ticket_ids:
                pipe.lrem('pool:pending', 0, str(tid))
            pipe.execute()
        except Exception as e:
            current_app.logger.warning(f"Redis revoke cleanup failed: {e}")

    notify_all('file_revoked', {
        'file_id': file_id,
        'revoked_count': revoked_count,
        'completed_count': completed_count,
    })

    return {
        'success': True,
        'message': f'已撤回 {revoked_count} 条数据（已出票 {completed_count} 条不受影响）',
        'revoked_count': revoked_count,
        'completed_count': completed_count,
    }
