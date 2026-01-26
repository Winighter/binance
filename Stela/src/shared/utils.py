from .typings import *


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