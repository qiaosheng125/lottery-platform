"""
票池管理服务

生产环境使用 Redis + PostgreSQL 双层并发安全机制：
  Redis LPOP → 原子弹出 ticket_id（防多人同时抢）
  PostgreSQL SELECT FOR UPDATE SKIP LOCKED → 确保唯一分配

开发环境（SQLite）使用简化的单次查询 + ORM UPDATE。

性能说明：
  - 关键查询已建索引（idx_tickets_pool, idx_tickets_deadline, idx_tickets_user）
  - 每日万条级别数据建议配合 PostgreSQL 分区表（按业务日期）
  - 历史数据定期归档策略见 tasks/archive.py（待实现）
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List
from gevent.lock import BoundedSemaphore

from sqlalchemy import text
from flask import current_app

from extensions import db
from models.ticket import LotteryTicket
from models.file import UploadedFile
from utils.time_utils import beijing_now

# SQLite 环境下用 gevent 协程锁保证分票串行化，持锁期间其他协程可继续处理无关请求
_sqlite_assign_lock = BoundedSemaphore(1)


def _is_postgres() -> bool:
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    return 'postgresql' in uri or 'postgres' in uri


def _get_redis():
    from extensions import redis_client as rc
    return rc


def _build_blocked_condition(blocked_types: List[str]) -> tuple[str, dict]:
    """构建排除禁止彩种的SQL条件片段和参数"""
    if not blocked_types:
        return "", {}
    placeholders = ','.join([f':bt{i}' for i in range(len(blocked_types))])
    condition = f"AND (lottery_type IS NULL OR lottery_type NOT IN ({placeholders}))"
    params = {f'bt{i}': t for i, t in enumerate(blocked_types)}
    return condition, params


def _count_today_completed(user_id: int, business_date_start: datetime) -> int:
    """统计用户当前业务日期内已完成（completed）的票数"""
    return db.session.execute(
        text("""
            SELECT COUNT(*) FROM lottery_tickets
            WHERE assigned_user_id = :user_id
              AND status = 'completed'
              AND completed_at >= :start
        """),
        {'user_id': user_id, 'start': business_date_start}
    ).scalar() or 0


def _ensure_unique_batch_assigned_at(user_id: int, device_id: str, assigned_at: datetime) -> datetime:
    """
    Keep B-mode batch grouping stable by ensuring the current device does not reuse
    the exact same assigned_at timestamp across concurrent/rapid downloads.
    """
    latest_existing = LotteryTicket.query.filter(
        LotteryTicket.assigned_user_id == user_id,
        LotteryTicket.assigned_device_id == device_id,
        LotteryTicket.status == 'assigned',
        LotteryTicket.assigned_at.isnot(None),
    ).order_by(LotteryTicket.assigned_at.desc()).first()

    if latest_existing and latest_existing.assigned_at and latest_existing.assigned_at >= assigned_at:
        return latest_existing.assigned_at + timedelta(microseconds=1)
    return assigned_at


def assign_ticket_atomic(user_id: int, device_id: str, username: str, device_name: str = None,
                         daily_limit: int = None, blocked_lottery_types: List[str] = None) -> Optional[LotteryTicket]:
    """
    原子性地从票池分配一张票给用户。

    生产（PostgreSQL）：
      1. Redis LPOP 弹出一个 ticket_id
      2. SELECT FOR UPDATE SKIP LOCKED 确认并锁定
      3. UPDATE status='assigned'

    开发（SQLite）：使用 ORM 简化路径（无并发安全保证）

    Args:
        daily_limit: 每日可处理票数上限，None表示不限制
        blocked_lottery_types: 禁止接收的彩种列表，None或空列表表示不限制
    """
    rc = _get_redis()
    now = beijing_now()
    lock_until = now + timedelta(minutes=current_app.config.get('TICKET_LOCK_MINUTES', 30))

    blocked_types = blocked_lottery_types or []

    # ── SQLite dev path ──────────────────────────────────────────
    if not _is_postgres():
        with _sqlite_assign_lock:
            # 检查每日上限
            if daily_limit is not None:
                from utils.time_utils import get_today_noon
                business_start = get_today_noon()
                today_count = _count_today_completed(user_id, business_start)
                if today_count >= daily_limit:
                    return None

            blocked_condition, blocked_params = _build_blocked_condition(blocked_types)

            # 先找一张 pending 票的 id（排除禁止的彩种）
            row = db.session.execute(
                text(f"""
                    SELECT id FROM lottery_tickets
                    WHERE status = 'pending'
                      AND deadline_time > :now
                      {blocked_condition}
                    ORDER BY id
                    LIMIT 1
                """),
                {'now': now, **blocked_params}
            ).fetchone()
            if not row:
                return None
            ticket_id = row[0]
            # 原子 UPDATE：只有 status='pending' 时才成功
            updated = db.session.execute(
                text("""
                    UPDATE lottery_tickets
                    SET status = 'assigned',
                        assigned_user_id = :user_id,
                        assigned_username = :username,
                        assigned_device_id = :device_id,
                        assigned_device_name = :device_name,
                        assigned_at = :now,
                        locked_until = :lock_until,
                        version = version + 1
                    WHERE id = :id AND status = 'pending'
                """),
                {
                    'user_id': user_id, 'username': username,
                    'device_id': device_id, 'device_name': device_name,
                    'now': now, 'lock_until': lock_until, 'id': ticket_id,
                }
            ).rowcount
            if not updated:
                db.session.rollback()
                return None
            db.session.execute(
                text("""
                    UPDATE uploaded_files
                    SET pending_count = pending_count - 1,
                        assigned_count = assigned_count + 1
                    WHERE id = (SELECT source_file_id FROM lottery_tickets WHERE id = :id)
                      AND pending_count > 0
                """),
                {'id': ticket_id}
            )
            db.session.commit()
            return LotteryTicket.query.get(ticket_id)

    # ── PostgreSQL production path ────────────────────────────────
    # 检查每日上限
    if daily_limit is not None:
        from utils.time_utils import get_today_noon
        business_start = get_today_noon()
        today_count = _count_today_completed(user_id, business_start)
        if today_count >= daily_limit:
            return None

    blocked_condition, blocked_params = _build_blocked_condition(blocked_types)

    MAX_ATTEMPTS = 10
    for _ in range(MAX_ATTEMPTS):
        ticket_id = None
        if rc:
            try:
                ticket_id = rc.lpop('pool:pending')
            except Exception as e:
                current_app.logger.warning(f"Redis LPOP error: {e}")

        if ticket_id:
            ticket_id = int(ticket_id)
        else:
            result = db.session.execute(
                text(f"""
                    SELECT id FROM lottery_tickets
                    WHERE status = 'pending'
                      AND deadline_time > NOW()
                      {blocked_condition}
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                """),
                blocked_params
            ).fetchone()
            if not result:
                return None
            ticket_id = result[0]

        try:
            ticket = db.session.execute(
                text("""
                    SELECT * FROM lottery_tickets
                    WHERE id = :id AND status = 'pending'
                    FOR UPDATE SKIP LOCKED
                """),
                {'id': ticket_id}
            ).fetchone()

            if not ticket:
                continue

            if ticket.deadline_time and ticket.deadline_time < now:
                db.session.execute(
                    text("UPDATE lottery_tickets SET status='expired' WHERE id=:id"),
                    {'id': ticket_id}
                )
                if ticket.source_file_id:
                    db.session.execute(
                        text("""
                            UPDATE uploaded_files
                            SET pending_count = CASE
                                WHEN pending_count > 0 THEN pending_count - 1
                                ELSE 0
                            END
                            WHERE id = :file_id
                        """),
                        {'file_id': ticket.source_file_id}
                    )
                db.session.commit()
                continue

            if ticket.lottery_type and ticket.lottery_type in blocked_types:
                # 该票属于禁止彩种，放回 Redis 队列供其他用户使用
                if rc:
                    try:
                        rc.rpush('pool:pending', ticket_id)
                    except Exception:
                        pass
                continue

            db.session.execute(
                text("""
                    UPDATE lottery_tickets
                    SET status = 'assigned',
                        assigned_user_id = :user_id,
                        assigned_username = :username,
                        assigned_device_id = :device_id,
                        assigned_device_name = :device_name,
                        assigned_at = :now,
                        locked_until = :lock_until,
                        version = version + 1
                    WHERE id = :id AND status = 'pending'
                """),
                {
                    'user_id': user_id, 'username': username,
                    'device_id': device_id, 'device_name': device_name,
                    'now': now, 'lock_until': lock_until, 'id': ticket_id,
                }
            )

            db.session.execute(
                text("""
                    UPDATE uploaded_files
                    SET pending_count = pending_count - 1,
                        assigned_count = assigned_count + 1
                    WHERE id = (SELECT source_file_id FROM lottery_tickets WHERE id = :id)
                      AND pending_count > 0
                """),
                {'id': ticket_id}
            )

            db.session.commit()
            return LotteryTicket.query.get(ticket_id)

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"assign_ticket_atomic error for id {ticket_id}: {e}")
            return None

    return None


def complete_ticket(ticket_id: int, user_id: int) -> bool:
    """将 assigned 状态的票标记为 completed"""
    now = beijing_now()

    if not _is_postgres():
        ticket = LotteryTicket.query.filter_by(
            id=ticket_id, assigned_user_id=user_id, status='assigned'
        ).first()
        if not ticket:
            return False
        ticket.status = 'completed'
        ticket.completed_at = now
        ticket.version += 1
        file = UploadedFile.query.get(ticket.source_file_id)
        if file and file.assigned_count > 0:
            file.assigned_count -= 1
            file.completed_count += 1
        db.session.commit()
        return True

    rows = db.session.execute(
        text("""
            UPDATE lottery_tickets
            SET status = 'completed',
                completed_at = :now,
                version = version + 1
            WHERE id = :id
              AND assigned_user_id = :user_id
              AND status = 'assigned'
        """),
        {'id': ticket_id, 'user_id': user_id, 'now': now}
    ).rowcount

    if rows:
        db.session.execute(
            text("""
                UPDATE uploaded_files
                SET assigned_count = assigned_count - 1,
                    completed_count = completed_count + 1
                WHERE id = (SELECT source_file_id FROM lottery_tickets WHERE id = :id)
            """),
            {'id': ticket_id}
        )
        db.session.commit()
    return rows > 0


def assign_tickets_batch(
    user_id: int,
    device_id: str,
    username: str,
    count: int,
    device_name: str = None,
    max_processing: int = None,
    daily_limit: int = None,
    blocked_lottery_types: List[str] = None,
) -> tuple[List[LotteryTicket], str]:
    """
    B模式：按截止时间升序自动分配指定张数的票（服务器决定彩种和截止时间）
    每次只分配一种彩种的票。

    选择逻辑：
    1. 按截止时间升序排列所有彩种
    2. 优先选择第一个彩种
    3. 如果第一个彩种票数 < 请求数量，且有其他截止时间相同的彩种，则选择票数最多的彩种

    Args:
        max_processing: B模式用户处理中票数上限，None表示不限制
        daily_limit: 每日可处理票数上限，None表示不限制
        blocked_lottery_types: 禁止接收的彩种列表，None或空列表表示不限制

    Returns:
        (tickets, adjustment_message): 分配的票列表和调整提示消息（如果有调整）
    """
    now = _ensure_unique_batch_assigned_at(user_id, device_id, beijing_now())
    lock_until = now + timedelta(minutes=current_app.config.get('TICKET_LOCK_MINUTES', 30))
    RESERVE = 20  # B模式至少保留20张给A模式/管理员上传缓冲

    blocked_types = blocked_lottery_types or []

    if not _is_postgres():
        with _sqlite_assign_lock:
            adjustment_message = None

            # 检查每日上限（并发安全，在锁内）
            if daily_limit is not None:
                from utils.time_utils import get_today_noon
                business_start = get_today_noon()
                today_count = _count_today_completed(user_id, business_start)
                if today_count >= daily_limit:
                    return [], '已达到今日处理上限'
                daily_remaining = daily_limit - today_count
                if count > daily_remaining:
                    count = daily_remaining
                    adjustment_message = f'已自动调整为{daily_remaining}张（今日已处理{today_count}张，每日上限{daily_limit}张）'

            # 在锁内检查B模式用户的处理中票数上限（并发安全）
            if max_processing is not None:
                current_processing = db.session.execute(
                    text("SELECT COUNT(*) FROM lottery_tickets WHERE assigned_user_id = :user_id AND status = 'assigned'"),
                    {'user_id': user_id}
                ).scalar() or 0

                if current_processing >= max_processing:
                    return [], None  # 已达上限，返回空列表

                # 自动调整请求数量为剩余额度
                remaining = max_processing - current_processing
                if count > remaining:
                    count = remaining
                    adjustment_message = f'已自动调整为{remaining}张（当前处理中{current_processing}张，上限{max_processing}张）'

            blocked_condition, blocked_params = _build_blocked_condition(blocked_types)

            total_pending = db.session.execute(
                text(f"SELECT COUNT(*) FROM lottery_tickets WHERE status='pending' AND deadline_time > :now {blocked_condition}"),
                {'now': now, **blocked_params}
            ).scalar() or 0
            available = max(0, total_pending - RESERVE)
            if available <= 0:
                return [], None
            actual_count = min(count, available)

            # 查询所有可用彩种及其票数和截止时间（排除禁止的彩种）
            type_stats = db.session.execute(
                text(f"""
                    SELECT lottery_type, deadline_time, COUNT(*) as cnt
                    FROM lottery_tickets
                    WHERE status = 'pending' AND deadline_time > :now
                    {blocked_condition}
                    GROUP BY lottery_type, deadline_time
                    ORDER BY deadline_time, lottery_type
                """),
                {'now': now, **blocked_params}
            ).fetchall()

            if not type_stats:
                return [], None

            # 选择彩种逻辑
            selected_type = None
            selected_deadline = None

            # 第一个彩种（截止时间最早）
            first_type = type_stats[0].lottery_type
            first_deadline = type_stats[0].deadline_time
            first_count = type_stats[0].cnt

            # 如果第一个彩种票数足够，直接选择
            if first_count >= actual_count:
                selected_type = first_type
                selected_deadline = first_deadline
            else:
                # 第一个彩种票数不足，查找截止时间相同的其他彩种
                same_deadline_types = [
                    (r.lottery_type, r.cnt) for r in type_stats
                    if r.deadline_time == first_deadline
                ]
                # 选择票数最多的彩种
                if same_deadline_types:
                    selected_type, _ = max(same_deadline_types, key=lambda x: x[1])
                    selected_deadline = first_deadline
                else:
                    # 没有其他截止时间相同的彩种，选择第一个
                    selected_type = first_type
                    selected_deadline = first_deadline

            # 确认实际可用票数（防止票数不足）
            selected_count = next((r.cnt for r in type_stats
                                   if r.lottery_type == selected_type
                                   and r.deadline_time == selected_deadline), 0)
            actual_count = min(actual_count, selected_count)

            # 从选中的彩种分配票
            rows = db.session.execute(
                text("""
                    SELECT id FROM lottery_tickets
                    WHERE status = 'pending'
                      AND deadline_time > :now
                      AND lottery_type = :lottery_type
                      AND deadline_time = :deadline_time
                    ORDER BY id
                    LIMIT :count
                """),
                {'now': now, 'lottery_type': selected_type, 'deadline_time': selected_deadline, 'count': actual_count}
            ).fetchall()
            if not rows:
                return [], None
            ids = [r[0] for r in rows]
            # 原子 UPDATE：WHERE status='pending' 防止重复分配
            # SQLite不支持直接绑定tuple到IN子句，需要动态生成占位符
            placeholders = ','.join([f':id{i}' for i in range(len(ids))])
            id_params = {f'id{i}': tid for i, tid in enumerate(ids)}

            db.session.execute(
                text(f"""
                    UPDATE lottery_tickets
                    SET status = 'assigned',
                        assigned_user_id = :user_id,
                        assigned_username = :username,
                        assigned_device_id = :device_id,
                        assigned_device_name = :device_name,
                        assigned_at = :now,
                        locked_until = :lock_until,
                        version = version + 1
                    WHERE id IN ({placeholders})
                      AND status = 'pending'
                """),
                {
                    'user_id': user_id, 'username': username,
                    'device_id': device_id, 'device_name': device_name,
                    'now': now, 'lock_until': lock_until,
                    **id_params,
                }
            )
            for tid in ids:
                db.session.execute(
                    text("""
                        UPDATE uploaded_files
                        SET pending_count = pending_count - 1,
                            assigned_count = assigned_count + 1
                        WHERE id = (SELECT source_file_id FROM lottery_tickets WHERE id = :id)
                          AND pending_count > 0
                    """),
                    {'id': tid}
                )
            db.session.commit()
            tickets = LotteryTicket.query.filter(LotteryTicket.id.in_(ids)).all()
            return tickets, adjustment_message

    # PostgreSQL: 检查每日上限
    if daily_limit is not None:
        from utils.time_utils import get_today_noon
        business_start = get_today_noon()
        today_count = _count_today_completed(user_id, business_start)
        if today_count >= daily_limit:
            return [], '已达到今日处理上限'
        daily_remaining = daily_limit - today_count
        if count > daily_remaining:
            count = daily_remaining

    blocked_condition, blocked_params = _build_blocked_condition(blocked_types)

    # PostgreSQL: 查询所有可用彩种及其票数和截止时间（排除禁止的彩种）
    type_stats = db.session.execute(
        text(f"""
            SELECT lottery_type, deadline_time, COUNT(*) as cnt
            FROM lottery_tickets
            WHERE status = 'pending' AND deadline_time > NOW()
            {blocked_condition}
            GROUP BY lottery_type, deadline_time
            ORDER BY deadline_time, lottery_type
        """),
        blocked_params
    ).fetchall()

    if not type_stats:
        return [], None

    # 计算可用票数（扣除保留）
    total_pending = sum(r.cnt for r in type_stats)
    available = max(0, total_pending - RESERVE)
    if available <= 0:
        return [], None
    actual_count = min(count, available)

    # 选择彩种逻辑
    selected_type = None
    selected_deadline = None

    # 第一个彩种（截止时间最早）
    first_type = type_stats[0].lottery_type
    first_deadline = type_stats[0].deadline_time
    first_count = type_stats[0].cnt

    # 如果第一个彩种票数足够，直接选择
    if first_count >= actual_count:
        selected_type = first_type
        selected_deadline = first_deadline
    else:
        # 第一个彩种票数不足，查找截止时间相同的其他彩种
        same_deadline_types = [
            (r.lottery_type, r.cnt) for r in type_stats
            if r.deadline_time == first_deadline
        ]
        # 选择票数最多的彩种
        if same_deadline_types:
            selected_type, _ = max(same_deadline_types, key=lambda x: x[1])
            selected_deadline = first_deadline
        else:
            # 没有其他截止时间相同的彩种，选择第一个
            selected_type = first_type
            selected_deadline = first_deadline

    # 从选中的彩种分配票
    rows = db.session.execute(
        text("""
            SELECT id FROM lottery_tickets
            WHERE status = 'pending'
              AND deadline_time > NOW()
              AND lottery_type = :lottery_type
              AND deadline_time = :deadline_time
            ORDER BY id
            FOR UPDATE SKIP LOCKED
            LIMIT :count
        """),
        {'lottery_type': selected_type, 'deadline_time': selected_deadline, 'count': actual_count}
    ).fetchall()

    if not rows:
        return [], None

    ids = [r[0] for r in rows]

    db.session.execute(
        text("""
            UPDATE lottery_tickets
            SET status = 'assigned',
                assigned_user_id = :user_id,
                assigned_username = :username,
                assigned_device_id = :device_id,
                assigned_device_name = :device_name,
                assigned_at = :now,
                locked_until = :lock_until,
                version = version + 1
            WHERE id = ANY(:ids)
              AND status = 'pending'
        """),
        {
            'user_id': user_id, 'username': username,
            'device_id': device_id, 'device_name': device_name,
            'now': now, 'lock_until': lock_until, 'ids': ids,
        }
    )

    db.session.execute(
        text("""
            UPDATE uploaded_files f
            SET pending_count = pending_count - sub.cnt,
                assigned_count = assigned_count + sub.cnt
            FROM (
                SELECT source_file_id, COUNT(*) as cnt
                FROM lottery_tickets
                WHERE id = ANY(:ids)
                GROUP BY source_file_id
            ) sub
            WHERE f.id = sub.source_file_id
        """),
        {'ids': ids}
    )

    db.session.commit()
    return LotteryTicket.query.filter(LotteryTicket.id.in_(ids)).all(), None


def complete_tickets_batch(ticket_ids: List[int], user_id: int) -> int:
    """B模式：批量完成票"""
    now = beijing_now()

    if not _is_postgres():
        tickets = LotteryTicket.query.filter(
            LotteryTicket.id.in_(ticket_ids),
            LotteryTicket.assigned_user_id == user_id,
            LotteryTicket.status == 'assigned',
        ).all()
        for t in tickets:
            t.status = 'completed'
            t.completed_at = now
            t.version += 1
            file = UploadedFile.query.get(t.source_file_id)
            if file and file.assigned_count > 0:
                file.assigned_count -= 1
                file.completed_count += 1
        db.session.commit()
        return len(tickets)

    rows = db.session.execute(
        text("""
            UPDATE lottery_tickets
            SET status = 'completed',
                completed_at = :now,
                version = version + 1
            WHERE id = ANY(:ids)
              AND assigned_user_id = :user_id
              AND status = 'assigned'
        """),
        {'ids': ticket_ids, 'user_id': user_id, 'now': now}
    ).rowcount

    if rows:
        db.session.execute(
            text("""
                UPDATE uploaded_files f
                SET assigned_count = assigned_count - sub.cnt,
                    completed_count = completed_count + sub.cnt
                FROM (
                    SELECT source_file_id, COUNT(*) as cnt
                    FROM lottery_tickets
                    WHERE id = ANY(:ids)
                    GROUP BY source_file_id
                ) sub
                WHERE f.id = sub.source_file_id
            """),
            {'ids': ticket_ids}
        )
        db.session.commit()

    return rows


def finalize_ticket(ticket_id: int, user_id: int, final_status: str = 'completed') -> bool:
    """Finalize a single assigned ticket as completed or expired."""
    completed_count = 1 if final_status != 'expired' else 0
    result = finalize_tickets_batch([ticket_id], user_id, completed_count=completed_count)
    return (result['completed_count'] + result['expired_count']) > 0


def finalize_tickets_batch(ticket_ids: List[int], user_id: int, completed_count: int = None) -> dict:
    """Finalize an assigned batch, completing the first N tickets and expiring the rest."""
    if not ticket_ids:
        return {'completed_count': 0, 'expired_count': 0}

    total = len(ticket_ids)
    if completed_count is None:
        completed_count = total
    completed_count = max(0, min(int(completed_count), total))

    completed_ids = list(ticket_ids[:completed_count])
    expired_ids = list(ticket_ids[completed_count:])
    now = beijing_now()

    if not _is_postgres():
        tickets = LotteryTicket.query.filter(
            LotteryTicket.id.in_(ticket_ids),
            LotteryTicket.assigned_user_id == user_id,
            LotteryTicket.status == 'assigned',
        ).all()
        ticket_map = {ticket.id: ticket for ticket in tickets}

        completed_total = 0
        expired_total = 0

        for current_id in completed_ids:
            ticket = ticket_map.get(current_id)
            if not ticket:
                continue
            ticket.status = 'completed'
            ticket.completed_at = now
            ticket.version += 1
            file = UploadedFile.query.get(ticket.source_file_id)
            if file and file.assigned_count > 0:
                file.assigned_count -= 1
                file.completed_count += 1
            completed_total += 1

        for current_id in expired_ids:
            ticket = ticket_map.get(current_id)
            if not ticket:
                continue
            ticket.status = 'expired'
            ticket.version += 1
            file = UploadedFile.query.get(ticket.source_file_id)
            if file and file.assigned_count > 0:
                file.assigned_count -= 1
            expired_total += 1

        db.session.commit()
        return {'completed_count': completed_total, 'expired_count': expired_total}

    existing_ids = {
        row.id
        for row in db.session.execute(
            text("""
                SELECT id
                FROM lottery_tickets
                WHERE id = ANY(:ids)
                  AND assigned_user_id = :user_id
                  AND status = 'assigned'
            """),
            {'ids': ticket_ids, 'user_id': user_id}
        ).fetchall()
    }
    valid_completed_ids = [current_id for current_id in completed_ids if current_id in existing_ids]
    valid_expired_ids = [current_id for current_id in expired_ids if current_id in existing_ids]

    if valid_completed_ids:
        db.session.execute(
            text("""
                UPDATE lottery_tickets
                SET status = 'completed',
                    completed_at = :now,
                    version = version + 1
                WHERE id = ANY(:ids)
                  AND assigned_user_id = :user_id
                  AND status = 'assigned'
            """),
            {'ids': valid_completed_ids, 'user_id': user_id, 'now': now}
        )
        db.session.execute(
            text("""
                UPDATE uploaded_files f
                SET assigned_count = assigned_count - sub.cnt,
                    completed_count = completed_count + sub.cnt
                FROM (
                    SELECT source_file_id, COUNT(*) as cnt
                    FROM lottery_tickets
                    WHERE id = ANY(:ids)
                    GROUP BY source_file_id
                ) sub
                WHERE f.id = sub.source_file_id
            """),
            {'ids': valid_completed_ids}
        )

    if valid_expired_ids:
        db.session.execute(
            text("""
                UPDATE lottery_tickets
                SET status = 'expired',
                    version = version + 1
                WHERE id = ANY(:ids)
                  AND assigned_user_id = :user_id
                  AND status = 'assigned'
            """),
            {'ids': valid_expired_ids, 'user_id': user_id}
        )
        db.session.execute(
            text("""
                UPDATE uploaded_files f
                SET assigned_count = assigned_count - sub.cnt
                FROM (
                    SELECT source_file_id, COUNT(*) as cnt
                    FROM lottery_tickets
                    WHERE id = ANY(:ids)
                    GROUP BY source_file_id
                ) sub
                WHERE f.id = sub.source_file_id
            """),
            {'ids': valid_expired_ids}
        )

    if valid_completed_ids or valid_expired_ids:
        db.session.commit()

    return {
        'completed_count': len(valid_completed_ids),
        'expired_count': len(valid_expired_ids),
    }


def get_pool_status() -> dict:
    """获取当前票池状态（用于实时展示）"""
    now = beijing_now()

    if not _is_postgres():
        from sqlalchemy import func
        from models.ticket import LotteryTicket as T
        from utils.time_utils import get_today_noon
        rows = db.session.query(
            T.lottery_type, T.deadline_time, func.count(T.id).label('count')
        ).filter(
            T.status == 'pending',
            T.deadline_time > now,
        ).group_by(T.lottery_type, T.deadline_time).order_by(T.deadline_time, T.lottery_type).all()

        total = sum(r.count for r in rows)
        by_type = [
            {
                'lottery_type': r.lottery_type,
                'deadline_time': r.deadline_time.isoformat() if r.deadline_time else None,
                'count': r.count,
            }
            for r in rows
        ]
        assigned = T.query.filter_by(status='assigned').count()

        # 今日完成数：按业务日 12:00-次日 12:00 统计
        today_start = get_today_noon()
        today_end = today_start + timedelta(days=1)

        completed_today = T.query.filter(
            T.status == 'completed',
            T.completed_at >= today_start,
            T.completed_at < today_end
        ).count()

        return {'total_pending': total, 'by_type': by_type, 'assigned': assigned, 'completed_today': completed_today}

    result = db.session.execute(
        text("""
            SELECT
                lottery_type,
                deadline_time,
                COUNT(*) as count
            FROM lottery_tickets
            WHERE status = 'pending'
              AND deadline_time > NOW()
            GROUP BY lottery_type, deadline_time
            ORDER BY deadline_time, lottery_type
        """)
    ).fetchall()

    total = sum(r.count for r in result)
    by_type = [
        {
            'lottery_type': r.lottery_type,
            'deadline_time': r.deadline_time.isoformat() if r.deadline_time else None,
            'count': r.count,
        }
        for r in result
    ]
    assigned = db.session.execute(
        text("SELECT COUNT(*) FROM lottery_tickets WHERE status='assigned'")
    ).scalar()
    from utils.time_utils import get_today_noon
    today_start = get_today_noon()
    today_end = today_start + timedelta(days=1)
    completed_today = db.session.execute(
        text("""
            SELECT COUNT(*) FROM lottery_tickets
            WHERE status = 'completed'
              AND completed_at >= :today_start
              AND completed_at < :today_end
        """),
        {'today_start': today_start, 'today_end': today_end}
    ).scalar()
    return {'total_pending': total, 'by_type': by_type, 'assigned': assigned or 0, 'completed_today': completed_today or 0}


def get_pool_total_pending() -> int:
    """B模式预查询：当前票池可供B模式使用的票数（总pending减去保留给A模式的20张）"""
    now = beijing_now()
    RESERVE = 20  # 至少保留给A模式/管理员上传缓冲

    if not _is_postgres():
        total = LotteryTicket.query.filter(
            LotteryTicket.status == 'pending',
            LotteryTicket.deadline_time > now,
        ).count()
        return max(0, total - RESERVE)

    result = db.session.execute(
        text("""
            SELECT COUNT(*) FROM lottery_tickets
            WHERE status = 'pending'
              AND deadline_time > NOW()
        """)
    ).scalar()
    return max(0, (result or 0) - RESERVE)
