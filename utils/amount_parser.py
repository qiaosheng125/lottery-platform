"""
彩票投注行金额解析模块

每行格式：{玩法代码}|{场次选项}|{基础倍数*基数}|{最终倍数}

示例:
  SPF|1=0,2=1,3=0/1/3,4=3,5=0/1/3,6=0|6*1|3
  CBF|1=20,2=90/42/41/40/31/30|2*1|2
  SF|1=3,2=0/3,3=0,4=3,5=0,6=3,7=0/3|7*1|5

金额 = 基础倍数 × 各场次选项数之积 × 最终倍数
"""

from decimal import Decimal
from typing import Optional, Tuple


SUPPORTED_TYPES = {'SPF', 'BQC', 'CBF', 'SF', 'JQS', 'SXP'}


def parse_ticket_line(raw_content: str) -> Optional[dict]:
    """
    解析一行彩票数据，返回结构化字典。

    Returns:
        {
          'bet_code': str,
          'fields': {field_no: [options]},
          'base_multiplier': int,
          'base': int,
          'final_multiplier': int,
        }
        或 None（解析失败）
    """
    raw_content = raw_content.strip()
    if not raw_content:
        return None

    parts = raw_content.split('|')
    if len(parts) < 4:
        return None

    bet_code = parts[0].strip().upper()
    if bet_code not in SUPPORTED_TYPES:
        return None

    # 解析场次选项: "1=0,2=1,3=0/1/3"
    fields_str = parts[1].strip()
    fields = {}
    for field_part in fields_str.split(','):
        field_part = field_part.strip()
        if '=' not in field_part:
            return None
        field_no, options_str = field_part.split('=', 1)
        cleaned_field_no = field_no.strip()
        if not cleaned_field_no or not cleaned_field_no.isdigit():
            return None
        options = options_str.split('/')
        cleaned_options = [o.strip() for o in options if o.strip()]
        if not cleaned_options:
            return None
        fields[cleaned_field_no] = cleaned_options

    if not fields:
        return None

    # 解析基础倍数*基数: "6*1"
    mult_str = parts[2].strip()
    try:
        base_mult, base = map(int, mult_str.split('*'))
    except Exception:
        return None
    if base != 1:
        return None
    if base_mult != len(fields):
        return None

    # 最终倍数
    try:
        final_multiplier = int(parts[3].strip())
    except Exception:
        return None
    if final_multiplier <= 0:
        return None

    return {
        'bet_code': bet_code,
        'fields': fields,
        'base_multiplier': base_mult,
        'base': base,
        'final_multiplier': final_multiplier,
    }


def calculate_ticket_amount(raw_content: str) -> Optional[Decimal]:
    """
    计算单行票的投注金额（元）。

    金额 = 2 × ∏(各场次选项数量) × final_multiplier
    固定基础倍率为 2，第三段 "N*1" 中的 N 是场次数量，不参与金额计算。
    示例: SF|1=3,2=0/3,3=0,4=3,5=0,6=3,7=0/3|7*1|5
          → 2 × (1×2×1×1×1×1×2) × 5 = 40
    """
    parsed = parse_ticket_line(raw_content)
    if not parsed:
        return None

    product = 1
    for options in parsed['fields'].values():
        product *= len(options)

    amount = 2 * product * parsed['final_multiplier']
    return Decimal(str(amount))
