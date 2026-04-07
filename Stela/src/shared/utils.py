from .typings import *
import pytz
from datetime import datetime

def round_step_size(value: Union[Decimal, float, str], step_size: Union[Decimal, float, str]) -> Decimal:
    """
    [통합 함수] 기준 단위(step_size)를 기반으로 값을 바이낸스 규격에 맞게 내림합니다.
    - value: 내가 계산한 원본 값 (예: 1.234567)
    - step_size: 거래소의 최소 단위 (예: 0.001)
    """
    if value is None or step_size is None:
        return Decimal('0')

    # 1. 모든 입력을 Decimal로 변환 (부동소수점 오차 방지)
    d_value = Decimal(str(value))
    d_step = Decimal(str(step_size))

    # 2. step_size가 0이거나 잘못된 경우 그대로 반환
    if d_step <= 0:
        return d_value

    # 3. quantize를 사용하여 즉시 자르기 (가장 핵심적인 한 줄)
    # 기존에 복잡하게 소수점 자리수를 int로 구하던 과정을 quantize가 내부적으로 대신 처리합니다.
    return d_value.quantize(d_step, rounding=ROUND_DOWN)

def round_tick_size(side, value: Union[Decimal, float, str], tick_size: Union[Decimal, float, str]) -> Decimal:
    """
    [통합 함수] 기준 단위(tick_size)를 기반으로 값을 바이낸스 규격에 맞게 내림합니다.
    - value: 내가 계산한 원본 값 (예: 1.234567)
    - tick_size: 거래소의 최소 단위 (예: 0.001)
    """
    if value is None or tick_size is None:
        return Decimal('0')

    # 1. 모든 입력을 Decimal로 변환 (부동소수점 오차 방지)
    d_value = Decimal(str(value))
    d_step = Decimal(str(tick_size))

    # 2. tick_size가 0이거나 잘못된 경우 그대로 반환
    if d_step <= 0:
        return d_value

    # 3. quantize를 사용하여 즉시 자르기 (가장 핵심적인 한 줄)
    # 기존에 복잡하게 소수점 자리수를 int로 구하던 과정을 quantize가 내부적으로 대신 처리합니다.
    result = d_value.quantize(d_step, rounding=ROUND_DOWN)
    if side == 'LONG':
        result += d_step
    elif side == 'SHORT':
        result -= d_step

    return result

def format_timestamp(ts_ms: Union[int, str, float], tz_name: str = 'Asia/Seoul') -> str:
    """
    타임스탬프(ms)를 읽기 쉬운 날짜 포맷 문자열로 변환합니다.
    기본값은 한국 시간(Asia/Seoul)입니다.
    """
    dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=pytz.UTC)
    local_dt = dt.astimezone(pytz.timezone(tz_name))
    return local_dt.strftime('%Y-%m-%d %H:%M:%S')

def get_session_label(ts_ms: Union[int, str]) -> List[str]:
    """타임스탬프를 분석하여 현재 세션명을 반환 (Asia, London, NewYork, Overlap)"""
    current_ts = int(ts_ms)
    one_hour_later_ts = current_ts + (3600 * 1000)
    # 내부 헬퍼 함수: 특정 타임스탬프의 세션명을 반환
    def calculate_session(ms: int) -> str:
        dt_utc = datetime.fromtimestamp(ms / 1000, tz=pytz.UTC)
        
        # 런던/뉴욕 시간대 설정
        dt_lon = dt_utc.astimezone(pytz.timezone('Europe/London'))
        dt_ny = dt_utc.astimezone(pytz.timezone('America/New_York'))

        # 각 시장의 업무 시간 (08:00 ~ 17:00)
        is_london = 8 <= dt_lon.hour < 17
        is_ny = 8 <= dt_ny.hour < 17
        
        if is_london and is_ny: return "Overlap"
        if is_london: return "London"
        if is_ny: return "NewYork"
        return "Asia"

    return [calculate_session(current_ts), calculate_session(one_hour_later_ts)]