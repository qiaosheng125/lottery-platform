from datetime import datetime, timedelta, date


def beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def get_business_reset_hour() -> int:
    try:
        from flask import current_app

        if not current_app:
            return 12
        from models.settings import SystemSettings

        hour = SystemSettings.get().daily_reset_hour
        if isinstance(hour, int) and 0 <= hour <= 23:
            return hour
    except Exception:
        pass
    return 12


def get_business_date(dt: datetime = None) -> date:
    """
    获取业务日期（以配置的每日重置小时为分割线）
    重置小时之前 → 昨天；重置小时及之后 → 今天
    """
    if dt is None:
        dt = beijing_now()
    reset_hour = get_business_reset_hour()
    if dt.hour < reset_hour:
        return (dt - timedelta(days=1)).date()
    return dt.date()


def get_today_noon() -> datetime:
    """获取当前业务日的起始时间（函数名保留以兼容旧调用方）。"""
    now = beijing_now()
    reset_hour = get_business_reset_hour()
    business_start = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
    if now.hour < reset_hour:
        business_start -= timedelta(days=1)
    return business_start


def get_business_window(target_date: date) -> tuple[datetime, datetime]:
    """根据业务日期返回 [当天重置时间, 次日重置时间) 时间窗口。"""
    reset_hour = get_business_reset_hour()
    start = datetime.combine(target_date, datetime.min.time()) + timedelta(hours=reset_hour)
    end = start + timedelta(days=1)
    return start, end


def resolve_deadline_datetime(hhmm_str: str, upload_dt: datetime = None) -> datetime:
    """
    将文件名中的 HH:MM 截止时间字符串解析为完整 datetime。

    规则：
      1. 基准日期：上传时北京时间 < 重置小时 → 昨天；否则 → 今天
      2. 若拼接后的截止时间 < 当天重置时间 → +1天（跨天夜间场次）
    """
    if upload_dt is None:
        upload_dt = beijing_now()

    try:
        hour, minute = map(int, hhmm_str.split('.'))
    except Exception:
        return None

    # 基准日期
    base_date = upload_dt.date()
    reset_hour = get_business_reset_hour()
    if upload_dt.hour < reset_hour:
        base_date = base_date - timedelta(days=1)

    deadline = datetime(base_date.year, base_date.month, base_date.day, hour, minute)

    # 若截止时间早于当天重置时间则跨天
    business_cutoff = upload_dt.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
    if deadline < business_cutoff:
        deadline += timedelta(days=1)

    return deadline
