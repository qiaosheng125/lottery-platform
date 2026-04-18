from datetime import datetime
from typing import Optional

from utils.time_utils import resolve_deadline_datetime


def _split_internal_code_and_lottery(segment: str):
    idx = 0
    while idx < len(segment) and segment[idx].isascii() and segment[idx].isalnum():
        idx += 1
    internal_code = segment[:idx]
    lottery_type = segment[idx:]
    if not internal_code or not lottery_type:
        return None, None
    return internal_code, lottery_type


def parse_filename(filename: str, upload_dt: datetime = None) -> Optional[dict]:
    name = filename.split('/')[-1].split('\\')[-1]
    if name.lower().endswith('.txt'):
        name = name[:-4]

    parts = name.split('_')
    if len(parts) not in (6, 7):
        return None

    identifier, combined_part, amount_part, count_part, deadline_hhmm, detail_period, *extra = parts
    if not identifier or not combined_part or not detail_period.isdigit():
        return None
    if not amount_part.startswith('金额') or not amount_part.endswith('元'):
        return None
    if not count_part.endswith('张'):
        return None
    if '倍投' not in combined_part:
        return None

    combined_without_suffix = combined_part[:-2] if combined_part.endswith('倍投') else None
    if not combined_without_suffix:
        return None

    multiplier_digits = ''
    idx = len(combined_without_suffix) - 1
    while idx >= 0 and combined_without_suffix[idx].isdigit():
        multiplier_digits = combined_without_suffix[idx] + multiplier_digits
        idx -= 1
    if not multiplier_digits:
        return None

    code_and_lottery = combined_without_suffix[:idx + 1]
    internal_code, lottery_type = _split_internal_code_and_lottery(code_and_lottery)
    if not internal_code or not lottery_type:
        return None

    amount_str = amount_part[len('金额'):-1]
    count_str = count_part[:-1]
    try:
        declared_amount = float(amount_str)
        declared_count = int(count_str)
        multiplier = int(multiplier_digits)
    except ValueError:
        return None

    deadline_dt = resolve_deadline_datetime(deadline_hhmm, upload_dt)
    return {
        'identifier': identifier,
        'internal_code': internal_code,
        'lottery_type': lottery_type,
        'multiplier': multiplier,
        'declared_amount': declared_amount,
        'declared_count': declared_count,
        'deadline_hhmm': deadline_hhmm,
        'deadline_time': deadline_dt,
        'detail_period': detail_period,
        'extra_param': extra[0] if extra else None,
    }

