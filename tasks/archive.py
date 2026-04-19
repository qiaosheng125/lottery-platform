"""
历史数据保留任务

当前策略不是长期归档，而是：
1. 主业务数据最多保留 30 天
2. 用户中奖记录最多只查最近 4 个业务日
3. 超过保留期的数据定时删除，降低主表和 uploads 目录压力
"""

from datetime import timedelta
import os

from flask import current_app

from extensions import db
from models.archive import ArchivedLotteryTicket
from models.audit import AuditLog
from models.file import UploadedFile
from models.result import MatchResult, ResultFile
from models.ticket import LotteryTicket
from models.winning import WinningRecord
from services.oss_service import delete_stored_image
from services.file_parser import delete_uploaded_txt_file
from utils.time_utils import beijing_now


def _resolve_result_file_path(upload_folder: str, stored_filename: str):
    normalized = (stored_filename or '').replace('\\', '/').strip()
    if not normalized:
        return None

    base_abs = os.path.abspath(upload_folder)
    candidate_abs = os.path.abspath(os.path.join(base_abs, normalized))
    try:
        if os.path.commonpath([base_abs, candidate_abs]) != base_abs:
            return None
    except ValueError:
        return None
    return candidate_abs


def _ticket_terminal_at(ticket: LotteryTicket):
    if ticket.status == 'completed':
        return ticket.completed_at
    return ticket.completed_at or ticket.deadline_time or ticket.assigned_at or ticket.admin_upload_time


def archive_old_tickets(days_ago=30):
    """
    清理超过保留期的终态票据。

    说明：
    - 名称保留为 archive_old_tickets 以兼容现有调度入口
    - 当前实际行为是“到期删除”，不是长期历史归档
    """
    cutoff_date = beijing_now() - timedelta(days=days_ago)

    candidates = LotteryTicket.query.filter(
        LotteryTicket.status.in_(['completed', 'revoked', 'expired'])
    ).all()

    to_delete = [
        ticket
        for ticket in candidates
        if _ticket_terminal_at(ticket) is not None and _ticket_terminal_at(ticket) < cutoff_date
    ]

    if not to_delete:
        current_app.logger.info('无需清理历史票据（%s天前）', days_ago)
        return 0

    ticket_ids = [ticket.id for ticket in to_delete]

    winning_records = WinningRecord.query.filter(WinningRecord.ticket_id.in_(ticket_ids)).all()
    for winning_record in winning_records:
        delete_stored_image(winning_record.image_oss_key, winning_record.winning_image_url)
        db.session.delete(winning_record)
    ArchivedLotteryTicket.query.filter(
        ArchivedLotteryTicket.original_ticket_id.in_(ticket_ids)
    ).delete(synchronize_session=False)

    deleted_count = 0
    for ticket in to_delete:
        db.session.delete(ticket)
        deleted_count += 1

    db.session.commit()
    current_app.logger.info('已删除 %s 条超过保留期的历史票据（%s天前）', deleted_count, days_ago)
    return deleted_count


def archive_old_uploaded_txt_files(days_ago=30):
    """
    删除超过保留期且已闭环的原始 TXT 及其 UploadedFile 记录。
    """
    cutoff_date = beijing_now() - timedelta(days=days_ago)
    upload_folder = current_app.config['UPLOAD_FOLDER']

    candidates = UploadedFile.query.filter(
        UploadedFile.uploaded_at < cutoff_date,
        UploadedFile.pending_count == 0,
        UploadedFile.assigned_count == 0,
    ).all()

    deleted_count = 0
    for uploaded_file in candidates:
        remaining_ticket_count = LotteryTicket.query.filter_by(source_file_id=uploaded_file.id).count()
        if remaining_ticket_count > 0:
            continue

        winning_records = WinningRecord.query.filter_by(source_file_id=uploaded_file.id).all()
        for winning_record in winning_records:
            delete_stored_image(winning_record.image_oss_key, winning_record.winning_image_url)
            db.session.delete(winning_record)
        delete_uploaded_txt_file(uploaded_file, upload_folder)
        db.session.delete(uploaded_file)
        deleted_count += 1

    if deleted_count:
        db.session.commit()
        current_app.logger.info('已删除 %s 个超过保留期的原始TXT及文件记录（%s天前）', deleted_count, days_ago)
    else:
        db.session.rollback()
        current_app.logger.info('无需删除原始TXT（%s天前）', days_ago)

    return deleted_count


def purge_old_auxiliary_records(days_ago=30):
    """
    删除超过保留期的辅助历史数据：
    - 开奖/赛果文件
    - 赛果记录
    - 审计日志
    - 已存在的旧归档表数据
    """
    cutoff_date = beijing_now() - timedelta(days=days_ago)
    upload_folder = current_app.config['UPLOAD_FOLDER']

    MatchResult.query.filter(MatchResult.uploaded_at < cutoff_date).delete(synchronize_session=False)

    result_files = ResultFile.query.filter(ResultFile.uploaded_at < cutoff_date).all()
    for result_file in result_files:
        has_remaining_match_results = MatchResult.query.filter_by(result_file_id=result_file.id).first()
        if has_remaining_match_results:
            continue

        stored_path = _resolve_result_file_path(upload_folder, result_file.stored_filename)
        if stored_path and os.path.exists(stored_path):
            os.remove(stored_path)
        elif not stored_path and result_file.stored_filename:
            current_app.logger.warning(
                'Skip deleting result file outside upload dir: %s',
                result_file.stored_filename,
            )
        db.session.delete(result_file)

    AuditLog.query.filter(AuditLog.timestamp < cutoff_date).delete(synchronize_session=False)
    ArchivedLotteryTicket.query.filter(
        ArchivedLotteryTicket.terminal_at.isnot(None),
        ArchivedLotteryTicket.terminal_at < cutoff_date,
    ).delete(synchronize_session=False)

    db.session.commit()
    current_app.logger.info('已清理超过保留期的辅助历史数据（%s天前）', days_ago)
    return True


def vacuum_database():
    """
    SQLite: VACUUM 回收空间
    PostgreSQL: VACUUM ANALYZE 优化查询计划
    """
    try:
        db.session.execute(db.text('VACUUM'))
        db.session.commit()
        current_app.logger.info('数据库 VACUUM 完成')
    except Exception as e:
        current_app.logger.warning(f'VACUUM 失败: {e}')
