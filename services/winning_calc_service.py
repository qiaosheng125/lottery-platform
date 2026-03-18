"""
中奖计算服务

赛果上传后自动触发的异步批量中奖计算任务。
"""

from decimal import Decimal

from flask import current_app

from extensions import db
from models.result import MatchResult
from models.ticket import LotteryTicket
from utils.time_utils import beijing_now
from utils.winning_calculator import calculate_winning


def process_match_result(match_result_id: int, app=None):
    """
    赛果上传后自动触发的中奖计算任务（在 APScheduler 后台线程中执行）。
    """
    from app import create_app
    if app is None:
        app = create_app()

    with app.app_context():
        match_result = MatchResult.query.get(match_result_id)
        if not match_result:
            return

        match_result.calc_status = 'processing'
        match_result.calc_started_at = beijing_now()
        db.session.commit()

        try:
            # Query all completed tickets for this period
            tickets = LotteryTicket.query.filter_by(
                detail_period=match_result.detail_period,
                status='completed',
            ).all()

            winning_count = 0
            total_amount = Decimal('0')

            for ticket in tickets:
                try:
                    is_win, gross, net, tax = calculate_winning(
                        raw_content=ticket.raw_content,
                        result_data=match_result.result_data,
                        multiplier=ticket.multiplier or 1,
                    )
                    ticket.is_winning = is_win
                    if is_win:
                        ticket.winning_gross = gross
                        ticket.winning_amount = net
                        ticket.winning_tax = tax
                        winning_count += 1
                        total_amount += net
                    else:
                        ticket.winning_gross = None
                        ticket.winning_amount = None
                        ticket.winning_tax = None
                except Exception as e:
                    current_app.logger.warning(f"Winning calc error for ticket {ticket.id}: {e}")
                    ticket.is_winning = False

            match_result.calc_status = 'done'
            match_result.calc_finished_at = beijing_now()
            match_result.tickets_total = len(tickets)
            match_result.tickets_winning = winning_count
            match_result.total_winning_amount = total_amount
            db.session.commit()

            # Notify admins
            from services.notify_service import notify_admins
            notify_admins('winning_calc_done', {
                'period': match_result.detail_period,
                'winning_count': winning_count,
                'total_amount': float(total_amount),
                'tickets_total': len(tickets),
            })

        except Exception as e:
            current_app.logger.error(f"process_match_result error: {e}")
            match_result.calc_status = 'error'
            db.session.commit()
