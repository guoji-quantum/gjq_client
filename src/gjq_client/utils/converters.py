
from datetime import datetime, timedelta, timezone
from typing import Any
from dateutil import tz, parser


def utc_to_local(utc_dt: datetime | str) -> datetime:
    """将 UTC ``datetime`` 对象或字符串转换为本地时区的 ``datetime``。

    Args:
        utc_dt: 输入的 UTC ``datetime`` 或字符串。

    Returns:
        带有本地时区的 ``datetime`` 对象。

    Raises:
        TypeError: 如果输入参数无效。
    """
    if isinstance(utc_dt, str):
        utc_dt = parser.parse(utc_dt)
    if not isinstance(utc_dt, datetime):
        raise TypeError("Input `utc_dt` is not string or datetime.")
    utc_dt = utc_dt.replace(tzinfo=timezone.utc)  # type: ignore[arg-type]
    local_dt = utc_dt.astimezone(tz.tzlocal())  # type: ignore[attr-defined]
    return local_dt


def local_to_utc(local_dt: datetime | str) -> datetime:
    """将本地时区的 ``datetime`` 对象或字符串转换为 UTC ``datetime``。

    Args:
        local_dt: 输入的本地时区 ``datetime`` 或字符串。

    Returns:
        一个表示 UTC 时间的 ``datetime`` 对象。

    Raises:
        TypeError: 如果输入参数无效。
    """
    if isinstance(local_dt, str):
        local_dt = parser.parse(local_dt)
    if not isinstance(local_dt, datetime):
        raise TypeError("Input `local_dt` is not string or datetime.")

    # Input is considered local if it's ``utcoffset()`` is ``None`` or none-zero.
    if local_dt.utcoffset() is None or local_dt.utcoffset() != timedelta(0):
        local_dt = local_dt.replace(tzinfo=tz.tzlocal())
        return local_dt.astimezone(tz.UTC)
    return local_dt  # Already in UTC.


def utc_to_local_all(data: Any) -> Any:
    """递归地将输入数据中的所有 UTC ``datetime`` 对象转换为本地时区的 ``datetime``。

    Args:
        data: 要转换的数据。

    Returns:
        已转换的数据。
    """
    if isinstance(data, datetime):
        return utc_to_local(data)
    elif isinstance(data, list):
        return [utc_to_local_all(elem) for elem in data]
    elif isinstance(data, dict):
        return {key: utc_to_local_all(elem) for key, elem in data.items()}
    return data