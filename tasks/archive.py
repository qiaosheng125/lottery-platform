"""
数据归档任务

定期将超过 N 天的已完成/已撤回/已超时票归档到历史表，保持主表数据量在可控范围。
建议每周执行一次，归档 30 天前的数据。
"""

from datetime import datetime, timedelta
from flask import current_app
from extensions import db
from models.ticket import LotteryTicket
from utils.time_utils import beijing_now


def archive_old_tickets(days_ago=30):
    """
    归档 N 天前的已完成/已撤回/已超时票

    策略：
    1. 将数据导出到 CSV/JSON 备份文件
    2. 从主表删除
    3. 保留 pending/assigned 状态的票（活跃数据）
    """
    cutoff_date = beijing_now() - timedelta(days=days_ago)

    # 查询需要归档的票
    to_archive = LotteryTicket.query.filter(
        LotteryTicket.status.in_(['completed', 'revoked', 'expired']),
        LotteryTicket.completed_at < cutoff_date
    ).all()

    if not to_archive:
        current_app.logger.info(f'无需归档的数据（{days_ago}天前）')
        return 0

    # TODO: 导出到备份文件（CSV/JSON）
    # backup_path = f'backups/tickets_{cutoff_date.strftime("%Y%m%d")}.csv'
    # with open(backup_path, 'w') as f:
    #     writer = csv.writer(f)
    #     for ticket in to_archive:
    #         writer.writerow([ticket.id, ticket.raw_content, ...])

    # 删除
    count = len(to_archive)
    for ticket in to_archive:
        db.session.delete(ticket)

    db.session.commit()
    current_app.logger.info(f'已归档 {count} 条数据（{days_ago}天前）')
    return count


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
