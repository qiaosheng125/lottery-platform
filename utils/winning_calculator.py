"""
中奖计算模块

基于 BettingCalculator 逻辑扩展，增加"对比赛果"功能。

赛果数据格式 (result_data):
{
  "61": {"SPF": {"result": "3", "sp": 1.85}, "CBF": {"result": "1-3", "sp": 11.514}, ...},
  "62": {...},
  ...
}

延期场次：result 字段值为 "延期" 或 "postponed"，该场次任意选项均视为中奖，SP值取1.0。

投注行格式: SPF|1=0,2=1,3=0/1/3,4=3,5=0/1/3,6=0|6*1|3

中奖逻辑（串关）：
  - 对于每个可能的串关组合（从各场次各选一个选项）：
    - 若所有场次选项均与赛果匹配（或赛果为延期）→ 该组合中奖
    - 中奖金额 = 各场次SP值之积 × 2元(基注) × 倍投数 × 1.3(系数)
  - 总中奖金额 = 所有中奖组合金额之和
  - 超过10000元需扣税20%

税后规则：
  - winning_amount <= 10000: 税后 = 原额
  - winning_amount > 10000: 税后 = 原额 × 0.8，扣税 = 原额 × 0.2
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

BASE_STAKE = Decimal('2')   # 基注 2元
BONUS_RATE = Decimal('1.3') # 奖金系数
TAX_THRESHOLD = Decimal('10000')
TAX_RATE = Decimal('0.2')

POSTPONED_KEYWORDS = {'延期', 'postponed', 'delayed', '-'}


def _is_postponed(result_str: str) -> bool:
    return result_str.strip().lower() in {k.lower() for k in POSTPONED_KEYWORDS}


def apply_tax(gross: Decimal) -> Tuple[Decimal, Decimal]:
    """
    返回 (税后金额, 扣税金额)
    超过10000元扣税20%
    """
    if gross > TAX_THRESHOLD:
        tax = (gross * TAX_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return gross - tax, tax
    return gross, Decimal('0')


def calculate_winning(
    raw_content: str,
    result_data: dict,
    multiplier: int
) -> Tuple[bool, Decimal, Decimal, Decimal]:
    """
    根据票的原始内容和赛果数据计算是否中奖及中奖金额。

    Args:
        raw_content: 彩票数据行原始内容
        result_data: 赛果+赔率（JSONB格式）
        multiplier: 倍投数（来自文件名）

    Returns:
        (is_winning, gross_amount, net_amount, tax_amount)
        gross_amount: 税前金额
        net_amount:   税后金额
        tax_amount:   扣税金额
    """
    parsed = parse_ticket_line(raw_content)
    if not parsed:
        return False, Decimal('0'), Decimal('0'), Decimal('0')

    bet_code = parsed['bet_code']
    result_key = BET_CODE_TO_RESULT_KEY.get(bet_code)
    if not result_key:
        return False, Decimal('0'), Decimal('0'), Decimal('0')

    fields = parsed['fields']  # {field_no: [options]}

    sorted_fields = sorted(fields.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0)
    field_nos = [f[0] for f in sorted_fields]
    field_options = [f[1] for f in sorted_fields]

    total_gross = Decimal('0')

    for combo in cartesian_product(*field_options):
        combo_sp = Decimal('1')
        all_win = True

        for field_no, selected_option in zip(field_nos, combo):
            match_info = result_data.get(field_no, {}).get(result_key)
            if not match_info:
                all_win = False
                break

            actual_result = str(match_info.get('result', ''))
            sp_value = match_info.get('sp', 1.0)

            if _is_postponed(actual_result):
                # 延期场次：任意选项视为中奖，SP=1.0
                combo_sp *= Decimal('1.0')
            elif selected_option != actual_result:
                all_win = False
                break
            else:
                combo_sp *= Decimal(str(sp_value))

        if all_win:
            combo_gross = combo_sp * BASE_STAKE * Decimal(str(multiplier)) * BONUS_RATE
            total_gross += combo_gross

    total_gross = total_gross.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    is_winning = total_gross > 0
    net_amount, tax_amount = apply_tax(total_gross)

    return is_winning, total_gross, net_amount, tax_amount

