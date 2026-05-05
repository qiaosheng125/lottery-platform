"""
文件解析服务

处理 TXT 文件上传：解析文件名、解析每行内容、批量入库、推入 Redis 队列。
"""

import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from gevent.lock import BoundedSemaphore

from flask import current_app
from sqlalchemy import func, text

from extensions import db
from models.file import UploadedFile
from models.ticket import LotteryTicket
from models.audit import AuditLog
from utils.filename_parser import parse_filename
from utils.amount_parser import calculate_ticket_amount, parse_ticket_line
from utils.time_utils import beijing_now, get_business_date, get_business_window, get_today_noon


_sqlite_upload_lock = BoundedSemaphore(1)
_sqlite_pending_upload_keys = set()

_LOTTERY_TYPE_ALIASES = {
    '鑳滃钩璐?': '胜平负',
    '璁╃悆鑳滃钩璐?': '让球胜平负',
    '姣斿垎': '比分',
    '???': '胜平负',
}


def _normalize_lottery_type(value: str) -> str:
    normalized = (value or '').strip()
    return _LOTTERY_TYPE_ALIASES.get(normalized, normalized)


def _is_postgres() -> bool:
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    return 'postgresql' in uri or 'postgres' in uri


@contextmanager
def _deduplicate_filename_upload_scope(filename: str, business_date):
    """Serialize same-business-day duplicate filename checks."""
    if _is_postgres():
        lock_key = f"{str(business_date)}:{filename.lower()}"
        db.session.execute(
            text("SELECT pg_advisory_xact_lock(:ns, hashtext(:lock_key))"),
            {'ns': 1002, 'lock_key': lock_key},
        )
        yield
        return

    with _sqlite_upload_lock:
        yield


def _enter_sqlite_duplicate_guard(filename: str, business_date) -> bool:
    guard_key = f"{str(business_date)}:{filename.lower()}"
    with _sqlite_upload_lock:
        if guard_key in _sqlite_pending_upload_keys:
            return False
        _sqlite_pending_upload_keys.add(guard_key)
        return True


def _leave_sqlite_duplicate_guard(filename: str, business_date) -> None:
    guard_key = f"{str(business_date)}:{filename.lower()}"
    with _sqlite_upload_lock:
        _sqlite_pending_upload_keys.discard(guard_key)


def _generate_display_id() -> str:
    """生成文件展示ID，格式: YYYY/MM/DD-NN"""
    now = beijing_now()
    date_str = get_business_date(now).strftime('%Y/%m/%d')
    # 找当前业务日 12:00 起的文件数量
    cutoff = get_today_noon()
    count = UploadedFile.query.filter(UploadedFile.uploaded_at >= cutoff).count()
    return f"{date_str}-{count + 1:02d}"


def build_uploaded_txt_relative_path(filename: str, upload_dt=None) -> str:
    upload_dt = upload_dt or beijing_now()
    safe_name = os.path.basename(filename)
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    unique_id = uuid.uuid4().hex[:8]
    business_date = get_business_date(upload_dt).isoformat()
    stored_name = f"{timestamp}_{unique_id}_{safe_name}"
    return os.path.join('txt', business_date, stored_name)


def resolve_uploaded_txt_path(stored_filename: str, upload_folder: str) -> str:
    normalized = (stored_filename or '').replace('\\', '/').strip()
    if not normalized:
        return ''

    upload_root = os.path.abspath(upload_folder)
    candidate = os.path.abspath(os.path.join(upload_root, normalized))
    try:
        if os.path.commonpath([upload_root, candidate]) != upload_root:
            return ''
    except ValueError:
        return ''
    return candidate


def archive_uploaded_txt_file(uploaded_file: UploadedFile, upload_folder: str) -> bool:
    current_path = resolve_uploaded_txt_path(uploaded_file.stored_filename, upload_folder)
    if not current_path:
        current_app.logger.warning(
            'Skip archiving uploaded txt outside upload dir: %s',
            uploaded_file.stored_filename,
        )
        return False
    if not os.path.exists(current_path):
        return False

    normalized = uploaded_file.stored_filename.replace('\\', '/')
    if normalized.startswith('archive/'):
        return False

    if normalized.startswith('txt/'):
        archive_relative = os.path.join('archive', uploaded_file.stored_filename)
    else:
        business_date = get_business_date(uploaded_file.uploaded_at or beijing_now()).isoformat()
        archive_relative = os.path.join('archive', 'txt', business_date, os.path.basename(uploaded_file.stored_filename))

    archive_path = os.path.join(upload_folder, archive_relative)
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    shutil.move(current_path, archive_path)
    uploaded_file.stored_filename = archive_relative
    return True


def delete_uploaded_txt_file(uploaded_file: UploadedFile, upload_folder: str) -> bool:
    current_path = resolve_uploaded_txt_path(uploaded_file.stored_filename, upload_folder)
    if not current_path:
        current_app.logger.warning(
            'Skip deleting uploaded txt outside upload dir: %s',
            uploaded_file.stored_filename,
        )
        return False
    if not os.path.exists(current_path):
        return False
    os.remove(current_path)
    return True


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

    filename = os.path.basename(file_storage.filename or '')
    upload_folder = current_app.config['UPLOAD_FOLDER']
    upload_dt = beijing_now()
    stored_filename = build_uploaded_txt_relative_path(filename, upload_dt)
    file_path = os.path.join(upload_folder, stored_filename)

    # Parse filename
    parsed_meta = parse_filename(filename, upload_dt)
    if not parsed_meta:
        return {'success': False, 'message': f'文件名格式不正确: {filename}', 'file_id': None, 'filename': filename}
    parsed_meta['lottery_type'] = _normalize_lottery_type(parsed_meta.get('lottery_type'))
    internal_code = parsed_meta['internal_code']

    business_date = get_business_date(upload_dt)
    duplicate_guard_key = internal_code
    if _is_postgres():
        db.session.execute(
            text("SELECT pg_advisory_xact_lock(:ns, hashtext(:lock_key))"),
            {'ns': 1002, 'lock_key': f"{str(business_date)}:{duplicate_guard_key.lower()}"},
        )
    else:
        if not _enter_sqlite_duplicate_guard(duplicate_guard_key, business_date):
            return {
                'success': False,
                'message': f'当前业务日内已上传同名文件或相同内部编号文件: {filename}',
                'file_id': None,
                'filename': filename,
            }

    business_start, business_end = get_business_window(business_date)
    existing_same_name = UploadedFile.query.filter(
        func.lower(UploadedFile.original_filename) == filename.lower(),
        UploadedFile.uploaded_at >= business_start,
        UploadedFile.uploaded_at < business_end,
    ).first()
    if existing_same_name:
        if not _is_postgres():
            _leave_sqlite_duplicate_guard(duplicate_guard_key, business_date)
        return {
            'success': False,
            'message': f'当前业务日内已上传同名文件: {filename}',
            'file_id': None,
            'filename': filename,
        }

    existing_same_internal_code = UploadedFile.query.filter(
        func.lower(UploadedFile.internal_code) == internal_code.lower(),
        UploadedFile.uploaded_at >= business_start,
        UploadedFile.uploaded_at < business_end,
    ).first()
    if existing_same_internal_code:
        if not _is_postgres():
            _leave_sqlite_duplicate_guard(duplicate_guard_key, business_date)
        return {
            'success': False,
            'message': f'当前业务日内已上传相同内部编号文件: {internal_code}',
            'file_id': None,
            'filename': filename,
        }

    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    file_storage.save(file_path)

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
        try:
            with open(file_path, 'r', encoding='gbk') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            db.session.rollback()
            os.remove(file_path)
            if not _is_postgres():
                _leave_sqlite_duplicate_guard(duplicate_guard_key, business_date)
            return {
                'success': False,
                'message': '文件编码无法识别，请使用 UTF-8 或 GBK',
                'file_id': None,
                'filename': filename,
            }

    ticket_ids = []
    initial_ticket_status = 'expired' if parsed_meta['deadline_time'] and parsed_meta['deadline_time'] <= upload_dt else 'pending'
    lottery_code_map = {
        '胜平负': 'SPF',
        '让球胜平负': 'SPF',
        '比分': 'CBF',
        '总进球': 'JQS',
        '总进球数': 'JQS',
        '半全场': 'BQC',
        '上下盘': 'SXP',
        '上下单双': 'SXP',
        '胜负': 'SF',
    }
    lottery_type = (parsed_meta.get('lottery_type') or '').strip()
    expected_bet_code = lottery_code_map.get(lottery_type)
    if not expected_bet_code:
        db.session.rollback()
        os.remove(file_path)
        if not _is_postgres():
            _leave_sqlite_duplicate_guard(duplicate_guard_key, business_date)
        return {
            'success': False,
            'message': f'文件名彩种不支持: {lottery_type}',
            'file_id': None,
            'filename': filename,
        }
    for line_no, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue

        parsed_ticket = parse_ticket_line(line)
        if not parsed_ticket:
            db.session.rollback()
            os.remove(file_path)
            if not _is_postgres():
                _leave_sqlite_duplicate_guard(duplicate_guard_key, business_date)
            return {
                'success': False,
                'message': f'第 {line_no} 行内容格式无效',
                'file_id': None,
                'filename': filename,
            }
        if expected_bet_code and parsed_ticket['bet_code'] != expected_bet_code:
            db.session.rollback()
            os.remove(file_path)
            if not _is_postgres():
                _leave_sqlite_duplicate_guard(duplicate_guard_key, business_date)
            return {
                'success': False,
                'message': f'第 {line_no} 行玩法与文件名彩种不一致',
                'file_id': None,
                'filename': filename,
            }
        if parsed_ticket['final_multiplier'] != parsed_meta['multiplier']:
            db.session.rollback()
            os.remove(file_path)
            if not _is_postgres():
                _leave_sqlite_duplicate_guard(duplicate_guard_key, business_date)
            return {
                'success': False,
                'message': f'第 {line_no} 行倍数与文件名倍数不一致',
                'file_id': None,
                'filename': filename,
            }
        amount = calculate_ticket_amount(line)
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
            status=initial_ticket_status,
            admin_upload_time=upload_dt,
        )
        tickets.append(ticket)

    if not tickets:
        db.session.rollback()
        os.remove(file_path)
        if not _is_postgres():
            _leave_sqlite_duplicate_guard(duplicate_guard_key, business_date)
        return {'success': False, 'message': '文件内容为空', 'file_id': None, 'filename': filename}

    declared_count = int(parsed_meta['declared_count'])
    declared_amount = Decimal(str(parsed_meta['declared_amount']))
    if len(tickets) != declared_count:
        db.session.rollback()
        os.remove(file_path)
        if not _is_postgres():
            _leave_sqlite_duplicate_guard(duplicate_guard_key, business_date)
        return {
            'success': False,
            'message': f'文件名声明 {declared_count} 张，实际解析 {len(tickets)} 张',
            'file_id': None,
            'filename': filename,
        }
    if total_amount != declared_amount:
        db.session.rollback()
        os.remove(file_path)
        if not _is_postgres():
            _leave_sqlite_duplicate_guard(duplicate_guard_key, business_date)
        return {
            'success': False,
            'message': f'文件名声明金额 {declared_amount} 元，实际解析金额 {total_amount} 元',
            'file_id': None,
            'filename': filename,
        }

    db.session.bulk_save_objects(tickets, return_defaults=True)

    # Update file counters
    uploaded_file.total_tickets = len(tickets)
    uploaded_file.pending_count = len(tickets) if initial_ticket_status == 'pending' else 0
    uploaded_file.actual_total_amount = total_amount

    db.session.flush()

    pending_ticket_count = uploaded_file.pending_count
    expired_ticket_count = len(tickets) - pending_ticket_count

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
    if not _is_postgres():
        _leave_sqlite_duplicate_guard(duplicate_guard_key, business_date)

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
            'count': pending_ticket_count,
            'expired_count': expired_ticket_count,
            'deadline': parsed_meta['deadline_time'].isoformat() if parsed_meta['deadline_time'] else None,
            'file_id': uploaded_file.id,
        })
    except Exception:
        pass

    message = f'成功上传 {len(tickets)} 条数据'
    if expired_ticket_count:
        if pending_ticket_count:
            message += f'（其中 {expired_ticket_count} 条已过截止时间，已标记为过期）'
        else:
            message += '（全部已过截止时间，已标记为过期）'

    return {
        'success': True,
        'file_id': uploaded_file.id,
        'filename': filename,
        'message': message,
        'ticket_count': len(tickets),
        'pending_ticket_count': pending_ticket_count,
        'expired_ticket_count': expired_ticket_count,
    }


def revoke_file(file_id: int, admin_id: int) -> dict:
    """撤回文件：将文件及所有 pending/assigned 票标记为 revoked"""
    from extensions import redis_client
    from services.notify_service import notify_all

    uploaded_file = db.session.get(UploadedFile, file_id)
    if not uploaded_file:
        return {'success': False, 'message': '文件不存在'}
    if uploaded_file.status == 'revoked':
        return {'success': False, 'message': '文件已撤回'}
    current_status = uploaded_file.derived_status()
    if current_status != 'active':
        if current_status == 'exhausted':
            return {'success': False, 'message': '文件已完成，不能撤回'}
        if current_status == 'expired':
            return {'success': False, 'message': '文件已过期，不能撤回'}
        return {'success': False, 'message': '文件当前状态不允许撤回'}

    now = beijing_now()
    uploaded_file.status = 'revoked'
    uploaded_file.revoked_at = now
    uploaded_file.revoked_by = admin_id

    # Bulk update tickets
    revoked_count = LotteryTicket.query.filter(
        LotteryTicket.source_file_id == file_id,
        LotteryTicket.status.in_(['pending', 'assigned'])
    ).update({
        'status': 'revoked',
        'version': LotteryTicket.version + 1,
    }, synchronize_session=False)

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

    try:
        notify_all('file_revoked', {
            'file_id': file_id,
            'revoked_count': revoked_count,
            'completed_count': completed_count,
        })
    except Exception as e:
        current_app.logger.warning(f"file_revoked notify failed for file {file_id}: {e}")

    return {
        'success': True,
        'message': f'已撤回 {revoked_count} 条数据（已出票 {completed_count} 条不受影响）',
        'revoked_count': revoked_count,
        'completed_count': completed_count,
    }
