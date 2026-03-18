from datetime import datetime, timedelta, date


def beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def get_business_date(dt: datetime = None) -> date:
    """
    获取业务日期（以每天12点为分割线）
    12点前 → 昨天；12点及之后 → 今天
    """
    if dt is None:
        dt = beijing_now()
    if dt.hour < 12:
        return (dt - timedelta(days=1)).date()
    return dt.date()


def get_today_noon() -> datetime:
    """获取当天12:00（北京时间）"""
    now = beijing_now()
    noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    if now.hour < 12:
        noon -= timedelta(days=1)
    return noon


def resolve_deadline_datetime(hhmm_str: str, upload_dt: datetime = None) -> datetime:
    """
    将文件名中的 HH:MM 截止时间字符串解析为完整 datetime。

    规则：
      1. 基准日期：上传时北京时间 < 12:00 → 昨天；否则 → 今天
      2. 若拼接后的截止时间 < 今天12:00 → +1天（跨天夜间场次）
    """
    if upload_dt is None:
        upload_dt = beijing_now()

    try:
        hour, minute = map(int, hhmm_str.split('.'))
    except Exception:
        return None

    # 基准日期
    base_date = upload_dt.date()
    if upload_dt.hour < 12:
        base_date = base_date - timedelta(days=1)

    deadline = datetime(base_date.year, base_date.month, base_date.day, hour, minute)

    # 若截止时间早于今日12点则跨天
    today_noon = upload_dt.replace(hour=12, minute=0, second=0, microsecond=0)
    if deadline < today_noon:
        deadline += timedelta(days=1)

    return deadline
