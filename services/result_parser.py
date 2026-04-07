"""
赛果文件解析服务

解析赛果 TXT 文件，写入 MatchResult 表，然后触发中奖计算任务。

赛果文件格式（制表符分隔）:
序号  让球胜平负彩果  让球胜平负SP值  比分彩果  比分SP值  总进球数彩果  总进球数SP值  半全场彩果  半全场SP值  上下单双彩果  上下单双SP值  胜负序号  胜负彩果  胜负SP值
61    3              1.85           1-3       11.514   1            6.812         1-3       11.514  下单       6.206       61        胜       1.88
"""

import os
from typing import Optional

from flask import current_app

from extensions import db
from models.result import MatchResult, ResultFile
from models.audit import AuditLog
from utils.time_utils import beijing_now


# 列名到(玩法代码, 结果列索引, SP列索引)的映射
# 文件格式（0-based列索引，去掉序号列后）:
# 0:序号 1:SPF彩果 2:SPF_SP 3:CBF彩果 4:CBF_SP 5:JQS彩果 6:JQS_SP
# 7:BQC彩果 8:BQC_SP 9:SXP彩果 10:SXP_SP 11:SF序号 12:SF彩果 13:SF_SP
COLUMN_MAP = {
    'SPF': (1, 2),
    'CBF': (3, 4),
    'JQS': (5, 6),
    'BQC': (7, 8),
    'SXP': (9, 10),
    'SF':  (12, 13),
}

# SF结果映射 中文 → 数字
SF_RESULT_MAP = {'胜': '3', '负': '0', '平': '1'}

# SXP结果映射：文字 → 数字（投注时用数字，赛果是文字）
# 0=上单，1=上双，2=下单，3=下双
SXP_RESULT_MAP = {
    '上单': '0',
    '上双': '1',
    '下单': '2',
    '下双': '3',
}


def _parse_result_line(cols: list, seq_no: str) -> dict:
    """解析一行赛果，返回该场次的各玩法结果+SP字典"""
    def safe_get(idx):
        return cols[idx].strip() if idx < len(cols) else ''

    field_data = {}

    # SPF (让球胜平负)
    spf_result = safe_get(1)
    spf_sp = safe_get(2)
    if spf_result:
        field_data['SPF'] = {'result': spf_result, 'sp': float(spf_sp) if spf_sp else 0}

    # CBF (比分)
    cbf_result = safe_get(3)
    cbf_sp = safe_get(4)
    if cbf_result:
        field_data['CBF'] = {'result': cbf_result, 'sp': float(cbf_sp) if cbf_sp else 0}

    # JQS (总进球)
    jqs_result = safe_get(5)
    jqs_sp = safe_get(6)
    if jqs_result:
        field_data['JQS'] = {'result': jqs_result, 'sp': float(jqs_sp) if jqs_sp else 0}

    # BQC (半全场)
    bqc_result = safe_get(7)
    bqc_sp = safe_get(8)
    if bqc_result:
        field_data['BQC'] = {'result': bqc_result, 'sp': float(bqc_sp) if bqc_sp else 0}

    # SXP (上下单双) - 转换为数字
    sxp_result_raw = safe_get(9)
    sxp_sp = safe_get(10)
    if sxp_result_raw:
        sxp_result = SXP_RESULT_MAP.get(sxp_result_raw, sxp_result_raw)
        field_data['SXP'] = {'result': sxp_result, 'sp': float(sxp_sp) if sxp_sp else 0}

    # SF (胜负) - uses its own sequence number in col 11
    sf_seq = safe_get(11)
    sf_result_raw = safe_get(12)
    sf_sp = safe_get(13)
    if sf_result_raw:
        sf_result = SF_RESULT_MAP.get(sf_result_raw, sf_result_raw)
        field_data['SF'] = {'result': sf_result, 'sp': float(sf_sp) if sf_sp else 0, 'seq': sf_seq}

    return field_data


def parse_result_file(file_path: str, detail_period: str, uploader_id: int, result_file_id: int = None) -> dict:
    """
    解析赛果文件，写入 MatchResult 表。

    Returns:
        {'success': bool, 'periods': [str], 'count': int, 'error': str}
    """
    try:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='gbk') as f:
                lines = f.readlines()
    except Exception as e:
        return {'success': False, 'error': str(e), 'count': 0}

    result_data = {}  # {seq_no: {玩法: {result, sp}}}
    count = 0

    for line in lines:
        line = line.strip()
        if not line or '序号' in line:
            continue  # Skip header and empty lines

        # 处理带箭头的格式：如 "2→1" 提取箭头后的序号
        cols = line.split('\t')
        if len(cols) < 2:
            # Try space-separated
            import re
            cols = re.split(r'\s+', line)

        if not cols:
            continue

        # 第一列可能是 "2→1" 这样的格式，提取箭头后的数字
        first_col = cols[0].strip()
        if '→' in first_col:
            seq_no = first_col.split('→')[-1].strip()
        else:
            seq_no = first_col

        if not seq_no.isdigit():
            continue

        field_data = _parse_result_line(cols, seq_no)
        if field_data:
            result_data[seq_no] = field_data
            count += 1

    if not result_data:
        return {'success': False, 'error': '未能解析任何赛果数据', 'count': 0}

    # Upsert MatchResult
    existing = MatchResult.query.filter_by(detail_period=detail_period).first()
    if existing:
        existing.result_data = result_data
        existing.calc_status = 'pending'
        existing.calc_started_at = None
        existing.calc_finished_at = None
        existing.tickets_total = 0
        existing.tickets_winning = 0
        existing.total_winning_amount = 0
        existing.uploaded_at = beijing_now()
        existing.uploaded_by = uploader_id
        if result_file_id:
            existing.result_file_id = result_file_id
        match_result = existing
    else:
        match_result = MatchResult(
            detail_period=detail_period,
            result_data=result_data,
            result_file_id=result_file_id,
            uploaded_by=uploader_id,
        )
        db.session.add(match_result)

    db.session.flush()
    db.session.commit()

    return {'success': True, 'match_result_id': match_result.id, 'count': count}
