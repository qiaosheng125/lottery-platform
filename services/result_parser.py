"""
Parse result TXT files into MatchResult and preserve predicted/final SP independently.
"""

import copy
import hashlib
import re
import threading
from contextlib import contextmanager
from typing import Optional

from extensions import db
from models.result import MatchResult
from sqlalchemy import text
from utils.time_utils import beijing_now


SF_RESULT_MAP = {
    '\u80dc': '3',
    '\u8d1f': '0',
    '\u5e73': '1',
}

SXP_RESULT_MAP = {
    '\u4e0a\u5355': '0',
    '\u4e0a\u53cc': '1',
    '\u4e0b\u5355': '2',
    '\u4e0b\u53cc': '3',
}

UPLOAD_KIND_TO_SP_KEY = {
    'predicted': 'predicted_sp',
    'final': 'sp',
}


_period_locks_guard = threading.Lock()
_period_locks = {}


def _period_advisory_lock_key(detail_period: str, lottery_type: Optional[str] = None) -> int:
    scope = f"{detail_period}::{lottery_type or '*'}"
    digest = hashlib.blake2b(scope.encode('utf-8'), digest_size=8).digest()
    key = int.from_bytes(digest, byteorder='big', signed=False)
    if key >= (1 << 63):
        key -= (1 << 64)
    return key


@contextmanager
def _period_upload_lock(detail_period: str, lottery_type: Optional[str] = None):
    bind = db.session.get_bind()
    dialect = getattr(bind, 'dialect', None) if bind else None
    dialect_name = (getattr(dialect, 'name', '') or '').lower()
    if dialect_name == 'postgresql':
        db.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {'lock_key': _period_advisory_lock_key(detail_period, lottery_type)},
        )
        yield
        return

    lock_key = (detail_period, lottery_type or '*')
    with _period_locks_guard:
        lock = _period_locks.setdefault(lock_key, threading.Lock())
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def _safe_get(cols, idx):
    return cols[idx].strip() if idx < len(cols) else ''


def _parse_sp_value(raw_value: str):
    if raw_value == '':
        return None
    try:
        return float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'invalid sp value: {raw_value}') from exc


def _parse_result_line(cols: list) -> dict:
    field_data = {}

    spf_result = _safe_get(cols, 1)
    if spf_result:
        field_data['SPF'] = {'result': spf_result, 'sp': _parse_sp_value(_safe_get(cols, 2))}

    cbf_result = _safe_get(cols, 3)
    if cbf_result:
        field_data['CBF'] = {'result': cbf_result, 'sp': _parse_sp_value(_safe_get(cols, 4))}

    jqs_result = _safe_get(cols, 5)
    if jqs_result:
        field_data['JQS'] = {'result': jqs_result, 'sp': _parse_sp_value(_safe_get(cols, 6))}

    bqc_result = _safe_get(cols, 7)
    if bqc_result:
        field_data['BQC'] = {'result': bqc_result, 'sp': _parse_sp_value(_safe_get(cols, 8))}

    sxp_result_raw = _safe_get(cols, 9)
    if sxp_result_raw:
        field_data['SXP'] = {
            'result': SXP_RESULT_MAP.get(sxp_result_raw, sxp_result_raw),
            'sp': _parse_sp_value(_safe_get(cols, 10)),
        }

    sf_result_raw = _safe_get(cols, 12)
    if sf_result_raw:
        field_data['SF'] = {
            'result': SF_RESULT_MAP.get(sf_result_raw, sf_result_raw),
            'sp': _parse_sp_value(_safe_get(cols, 13)),
            'seq': _safe_get(cols, 11),
        }

    return field_data


def _extract_seq_no(first_col: str):
    normalized = first_col.strip()
    arrow = '\u2192'
    if arrow in normalized:
        normalized = normalized.split(arrow)[-1].strip()
    return normalized if normalized.isdigit() else None


def _clear_upload_kind(existing_data: dict, upload_kind: str) -> dict:
    sp_key = UPLOAD_KIND_TO_SP_KEY[upload_kind]
    cleaned = {}

    for seq_no, field_map in (existing_data or {}).items():
        next_field_map = {}
        for play_code, play_data in (field_map or {}).items():
            if not isinstance(play_data, dict):
                continue
            next_play_data = dict(play_data)
            next_play_data.pop(sp_key, None)
            if next_play_data.get('predicted_sp') is None and next_play_data.get('sp') is None:
                continue
            next_field_map[play_code] = next_play_data
        if next_field_map:
            cleaned[seq_no] = next_field_map

    return cleaned


def _merge_result_data(existing_data: dict, parsed_data: dict, upload_kind: str) -> dict:
    sp_key = UPLOAD_KIND_TO_SP_KEY[upload_kind]
    merged = copy.deepcopy(existing_data or {})

    for seq_no, field_map in parsed_data.items():
        seq_bucket = merged.setdefault(seq_no, {})
        for play_code, play_data in field_map.items():
            target = dict(seq_bucket.get(play_code) or {})
            target['result'] = play_data.get('result')
            if play_code == 'SF' and play_data.get('seq'):
                target['seq'] = play_data.get('seq')
            target[sp_key] = play_data.get('sp')
            seq_bucket[play_code] = target

    return merged


def _collect_upload_kind_keys(result_data: dict, upload_kind: str) -> set[tuple[str, str]]:
    sp_key = UPLOAD_KIND_TO_SP_KEY[upload_kind]
    keys = set()
    for seq_no, field_map in (result_data or {}).items():
        seq = str(seq_no)
        for play_code, play_data in (field_map or {}).items():
            if not isinstance(play_data, dict):
                continue
            if play_data.get(sp_key) is None:
                continue
            keys.add((seq, play_code))
    return keys


def _collect_parsed_keys(parsed_data: dict) -> set[tuple[str, str]]:
    keys = set()
    for seq_no, field_map in (parsed_data or {}).items():
        seq = str(seq_no)
        for play_code, play_data in (field_map or {}).items():
            if not isinstance(play_data, dict):
                continue
            if play_data.get('sp') is None:
                continue
            keys.add((seq, play_code))
    return keys


def parse_result_file(
    file_path: str,
    detail_period: str,
    uploader_id: int,
    result_file_id: int = None,
    upload_kind: str = 'final',
    lottery_type: Optional[str] = None,
) -> dict:
    """
    Parse a result file and update the latest MatchResult for the period.
    """
    if upload_kind not in UPLOAD_KIND_TO_SP_KEY:
        return {'success': False, 'error': 'invalid upload kind', 'count': 0}

    try:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='gbk') as f:
                lines = f.readlines()
    except Exception as exc:
        return {'success': False, 'error': str(exc), 'count': 0}

    parsed_data = {}
    count = 0
    header_keyword = '\u5e8f\u53f7'

    try:
        for raw_line in lines:
            line = raw_line.strip()
            if not line or header_keyword in line:
                continue

            cols = line.split('\t')
            if len(cols) < 2:
                cols = re.split(r'\s+', line)
            if not cols:
                continue

            seq_no = _extract_seq_no(cols[0])
            if not seq_no:
                continue

            field_data = _parse_result_line(cols)
            if field_data:
                parsed_data[seq_no] = field_data
    except ValueError as exc:
        return {'success': False, 'error': str(exc), 'count': 0}

    if not parsed_data:
        return {'success': False, 'error': '\u672a\u80fd\u89e3\u6790\u4efb\u4f55\u8d5b\u679c\u6570\u636e', 'count': 0}
    count = len(parsed_data)

    with _period_upload_lock(detail_period, lottery_type):
        existing_query = MatchResult.query.filter(MatchResult.detail_period == detail_period)
        if lottery_type is None:
            existing_query = existing_query.filter(MatchResult.lottery_type.is_(None))
        else:
            existing_query = existing_query.filter(MatchResult.lottery_type == lottery_type)

        existing = existing_query.order_by(
            MatchResult.uploaded_at.desc(),
            MatchResult.id.desc(),
        ).first()

        if existing:
            existing_keys = _collect_upload_kind_keys(existing.result_data or {}, upload_kind)
            incoming_keys = _collect_parsed_keys(parsed_data)
            if existing_keys and not existing_keys.issubset(incoming_keys):
                missing_keys = sorted(existing_keys - incoming_keys)
                missing_preview = ', '.join(f'{seq}:{play}' for seq, play in missing_keys[:5])
                db.session.rollback()
                return {
                    'success': False,
                    'error': (
                        f'incomplete {upload_kind} upload: missing '
                        f'{len(missing_keys)} existing entries ({missing_preview})'
                    ),
                    'count': 0,
                }

        base_data = _clear_upload_kind(existing.result_data if existing else {}, upload_kind)
        merged_data = _merge_result_data(base_data, parsed_data, upload_kind)

        if existing:
            existing.result_data = merged_data
            existing.calc_status = 'pending'
            existing.calc_started_at = None
            existing.calc_finished_at = None
            existing.tickets_total = 0
            existing.tickets_winning = 0
            existing.predicted_total_winning_amount = 0
            existing.total_winning_amount = 0
            existing.uploaded_at = beijing_now()
            existing.uploaded_by = uploader_id
            if result_file_id:
                existing.result_file_id = result_file_id
            match_result = existing
        else:
            match_result = MatchResult(
                detail_period=detail_period,
                lottery_type=lottery_type,
                result_data=merged_data,
                result_file_id=result_file_id,
                uploaded_by=uploader_id,
            )
            db.session.add(match_result)

        db.session.flush()
        db.session.commit()
        uploaded_at = match_result.uploaded_at.isoformat() if match_result.uploaded_at else None

    return {
        'success': True,
        'match_result_id': match_result.id,
        'count': count,
        'uploaded_at': uploaded_at,
        'calc_token': f"rf:{result_file_id}" if result_file_id is not None else (f"ts:{uploaded_at}" if uploaded_at else None),
    }
