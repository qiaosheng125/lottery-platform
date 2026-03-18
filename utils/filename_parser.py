import re
from typing import Optional
from utils.time_utils import resolve_deadline_datetime
from datetime import datetime


# 文件名格式示例:
# 岩_V99胜平负3倍投_金额600元_27张_21.55_26034.txt
# 军_V58比分2倍投_金额240元_11张_23.55_26034.txt
# 哈_P7上下盘3倍投_金额150元_7张_21.55_26034.txt

FILENAME_PATTERN = re.compile(
    r'^(?P<identifier>[^\s_]+)'       # identifier: 岩, 军, 哈 ...
    r'_(?P<internal_code>[A-Za-z0-9]+)'  # internal_code: V99, P7, W39...
    r'(?P<lottery_type>[^\d_]+)'      # lottery_type: 胜平负, 比分, 上下盘...
    r'(?P<multiplier>\d+)倍投'        # multiplier: 3
    r'_金额(?P<declared_amount>[\d.]+)元'
    r'_(?P<declared_count>\d+)张'
    r'_(?P<deadline_hhmm>\d{2}\.\d{2})'  # 21.55
    r'_(?P<detail_period>\d+)'        # 26034
    r'(?:\.txt)?$',
    re.UNICODE,
)


def parse_filename(filename: str, upload_dt: datetime = None) -> Optional[dict]:
    """
    解析彩票数据文件名，返回解析结果字典或 None（解析失败）。
    """
    # 去掉路径部分
    name = filename.split('/')[-1].split('\\')[-1]
    m = FILENAME_PATTERN.match(name)
    if not m:
        return None

    deadline_dt = resolve_deadline_datetime(m.group('deadline_hhmm'), upload_dt)

    return {
        'identifier': m.group('identifier'),
        'internal_code': m.group('internal_code'),
        'lottery_type': m.group('lottery_type'),
        'multiplier': int(m.group('multiplier')),
        'declared_amount': float(m.group('declared_amount')),
        'declared_count': int(m.group('declared_count')),
        'deadline_hhmm': m.group('deadline_hhmm'),
        'deadline_time': deadline_dt,
        'detail_period': m.group('detail_period'),
    }
