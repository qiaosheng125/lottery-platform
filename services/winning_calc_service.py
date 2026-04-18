"""
Winning calculation service for predicted/final result uploads.
"""

from datetime import datetime
from decimal import Decimal

from flask import current_app

from extensions import db
from models.result import MatchResult
from models.ticket import LotteryTicket
from models.winning import WinningRecord
from services.oss_service import delete_stored_image
from utils.time_utils import beijing_now
from utils.winning_calculator import calculate_winning


def _run_calculation(raw_content: str, result_data: dict, multiplier: int, sp_field: str):
    try:
        return calculate_winning(
            raw_content=raw_content,
            result_data=result_data,
            multiplier=multiplier,
            sp_field=sp_field,
        )
    except TypeError as exc:
        if 'sp_field' not in str(exc):
            raise
        return calculate_winning(raw_content, result_data, multiplier)


def _clear_ticket_amounts(ticket: LotteryTicket, clear_predicted: bool, clear_final: bool):
    if clear_predicted:
        ticket.predicted_winning_gross = None
        ticket.predicted_winning_amount = None
        ticket.predicted_winning_tax = None
    if clear_final:
        ticket.winning_gross = None
        ticket.winning_amount = None
        ticket.winning_tax = None


def _parse_expected_uploaded_at(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def process_match_result(match_result_id: int, expected_uploaded_at=None, app=None):
    from app import create_app

    if app is None:
        app = create_app()

    with app.app_context():
        expected_uploaded_at_dt = _parse_expected_uploaded_at(expected_uploaded_at)
        match_result = db.session.get(MatchResult, match_result_id)
        if not match_result:
            return
        if expected_uploaded_at_dt and match_result.uploaded_at != expected_uploaded_at_dt:
            current_app.logger.info(
                "Skip stale winning calc start for result %s (expected=%s actual=%s)",
                match_result_id,
                expected_uploaded_at_dt,
                match_result.uploaded_at,
            )
            return

        match_result.calc_status = 'processing'
        match_result.calc_started_at = beijing_now()
        db.session.commit()

        try:
            tickets = LotteryTicket.query.filter(
                LotteryTicket.detail_period == match_result.detail_period,
                LotteryTicket.status.in_(['completed', 'expired']),
            ).all()

            has_predicted_results = match_result.has_predicted_results()
            has_final_results = match_result.has_final_results()

            active_winning_count = 0
            active_total_amount = Decimal('0')
            predicted_total_amount = Decimal('0')

            for ticket in tickets:
                winning_record = WinningRecord.query.filter_by(ticket_id=ticket.id).first()
                try:
                    predicted_result = (False, Decimal('0'), Decimal('0'), Decimal('0'))
                    final_result = (False, Decimal('0'), Decimal('0'), Decimal('0'))

                    if has_predicted_results:
                        predicted_result = _run_calculation(
                            raw_content=ticket.raw_content,
                            result_data=match_result.result_data,
                            multiplier=ticket.multiplier or 1,
                            sp_field='predicted_sp',
                        )

                    if has_final_results:
                        final_result = _run_calculation(
                            raw_content=ticket.raw_content,
                            result_data=match_result.result_data,
                            multiplier=ticket.multiplier or 1,
                            sp_field='sp',
                        )

                    predicted_is_win, predicted_gross, predicted_net, predicted_tax = predicted_result
                    final_is_win, final_gross, final_net, final_tax = final_result

                    if predicted_is_win:
                        ticket.predicted_winning_gross = predicted_gross
                        ticket.predicted_winning_amount = predicted_net
                        ticket.predicted_winning_tax = predicted_tax
                        predicted_total_amount += predicted_net
                    else:
                        _clear_ticket_amounts(ticket, clear_predicted=True, clear_final=False)

                    if final_is_win:
                        ticket.winning_gross = final_gross
                        ticket.winning_amount = final_net
                        ticket.winning_tax = final_tax
                    else:
                        _clear_ticket_amounts(ticket, clear_predicted=False, clear_final=True)

                    active_is_win = final_is_win if has_final_results else predicted_is_win
                    active_net_amount = final_net if has_final_results else predicted_net

                    ticket.is_winning = active_is_win
                    if active_is_win:
                        active_winning_count += 1
                        active_total_amount += active_net_amount
                    else:
                        if winning_record:
                            delete_stored_image(winning_record.image_oss_key, winning_record.winning_image_url)
                            db.session.delete(winning_record)
                        ticket.winning_image_url = None
                except Exception as exc:
                    current_app.logger.warning("Winning calc error for ticket %s: %s", ticket.id, exc)
                    ticket.is_winning = False
                    _clear_ticket_amounts(ticket, clear_predicted=True, clear_final=True)
                    if winning_record:
                        delete_stored_image(winning_record.image_oss_key, winning_record.winning_image_url)
                        db.session.delete(winning_record)
                    ticket.winning_image_url = None

            if expected_uploaded_at_dt:
                latest_uploaded_at = db.session.query(MatchResult.uploaded_at).filter(
                    MatchResult.id == match_result_id
                ).scalar()
                if latest_uploaded_at != expected_uploaded_at_dt:
                    db.session.rollback()
                    current_app.logger.info(
                        "Skip stale winning calc commit for result %s (expected=%s actual=%s)",
                        match_result_id,
                        expected_uploaded_at_dt,
                        latest_uploaded_at,
                    )
                    return

            match_result.calc_status = 'done'
            match_result.calc_finished_at = beijing_now()
            match_result.tickets_total = len(tickets)
            match_result.tickets_winning = active_winning_count
            match_result.predicted_total_winning_amount = predicted_total_amount
            match_result.total_winning_amount = active_total_amount
            db.session.commit()

            from services.notify_service import notify_admins

            notify_admins('winning_calc_done', {
                'period': match_result.detail_period,
                'winning_count': active_winning_count,
                'total_amount': float(active_total_amount),
                'tickets_total': len(tickets),
            })
        except Exception as exc:
            current_app.logger.error("process_match_result error: %s", exc)
            match_result.calc_status = 'error'
            db.session.commit()
