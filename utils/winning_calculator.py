"""
Winning amount calculator shared by predicted and final result flows.
"""

from decimal import Decimal, ROUND_HALF_UP
from itertools import product as cartesian_product
from typing import Tuple

from utils.amount_parser import parse_ticket_line


BET_CODE_TO_RESULT_KEY = {
    'SPF': 'SPF',
    'BQC': 'BQC',
    'CBF': 'CBF',
    'SF': 'SF',
    'JQS': 'JQS',
    'SXP': 'SXP',
}

BASE_STAKE = Decimal('1')
BONUS_RATE = Decimal('1.3')
TAX_THRESHOLD = Decimal('10000')
TAX_RATE = Decimal('0.2')

POSTPONED_KEYWORDS = {
    '\u5ef6\u671f',
    'postponed',
    'delayed',
    '-',
}


def _is_postponed(result_str: str) -> bool:
    return (result_str or '').strip().lower() in {keyword.lower() for keyword in POSTPONED_KEYWORDS}


def _get_decimal_sp(match_info: dict, sp_field: str):
    sp_value = match_info.get(sp_field)
    if sp_value in (None, ''):
        return None
    return Decimal(str(sp_value))


def apply_tax(gross: Decimal) -> Tuple[Decimal, Decimal]:
    if gross > TAX_THRESHOLD:
        tax = (gross * TAX_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return gross - tax, tax
    return gross, Decimal('0')


def calculate_winning(
    raw_content: str,
    result_data: dict,
    multiplier: int,
    sp_field: str = 'sp',
) -> Tuple[bool, Decimal, Decimal, Decimal]:
    parsed = parse_ticket_line(raw_content)
    if not parsed:
        return False, Decimal('0'), Decimal('0'), Decimal('0')

    result_key = BET_CODE_TO_RESULT_KEY.get(parsed['bet_code'])
    if not result_key:
        return False, Decimal('0'), Decimal('0'), Decimal('0')

    sorted_fields = sorted(
        parsed['fields'].items(),
        key=lambda item: int(item[0]) if item[0].isdigit() else 0,
    )
    field_nos = [item[0] for item in sorted_fields]
    field_options = [item[1] for item in sorted_fields]

    total_gross = Decimal('0')

    for combo in cartesian_product(*field_options):
        combo_sp = Decimal('1')
        all_win = True

        for field_no, selected_option in zip(field_nos, combo):
            match_info = (result_data.get(field_no) or {}).get(result_key)
            if not match_info:
                all_win = False
                break

            actual_result = str(match_info.get('result', ''))
            if _is_postponed(actual_result):
                combo_sp *= Decimal('1.0')
                continue

            if selected_option != actual_result:
                all_win = False
                break

            decimal_sp = _get_decimal_sp(match_info, sp_field)
            if decimal_sp is None:
                all_win = False
                break
            combo_sp *= decimal_sp

        if all_win:
            total_gross += combo_sp * BASE_STAKE * Decimal(str(multiplier)) * BONUS_RATE

    total_gross = total_gross.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    is_winning = total_gross > 0
    net_amount, tax_amount = apply_tax(total_gross)
    return is_winning, total_gross, net_amount, tax_amount
