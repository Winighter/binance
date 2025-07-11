import time
import sys

def type_print(text, delay=0.05):
    """
    문자열을 키보드로 타이핑하듯이 콘솔에 출력합니다.

    Args:
        text (str): 출력할 문자열.
        delay (float): 각 문자 출력 사이의 지연 시간 (초). 기본값은 0.05초.
    """
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()  # 버퍼를 비워 바로 출력되도록 함
        time.sleep(delay)
    print() # 모든 문자열 출력 후 줄바꿈

# 사용 예시
if __name__ == "__main__":
    message1 = "안녕하세요! 파이썬으로 타이핑 효과를 내고 있습니다."
    message2 = "이것은 마치 제가 키보드를 직접 치는 것처럼 보일 거예요."
    message3 = "재미있죠? :) 속도 조절도 가능합니다."

    # type_print(message1)
    # type_print(message2, delay=0.03) # 더 빠르게 출력
    # type_print(message3, delay=0.1)  # 더 느리게 출력
    type_print("Start Binance...")