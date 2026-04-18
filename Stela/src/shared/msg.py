import logging
import os
import asyncio
import aiohttp
import settings
import threading
import queue
import io 
import sys
import settings as app_config
from .enums import *
from .typings import *

DISCORD_WEBHOOK_URL = 'https://discordapp.com/api/webhooks/1455113680357298283/dWzc47tuFZ0f9qZk-W6uCCHtJZhAzUT-G3jHRQAqF0ya4HXqjZ97HeU-WncDTCydt43y'


# 기본 로거를 설정합니다.
log_dir = os.path.join(os.path.dirname(__file__), '...')
log_file_path = os.path.join(log_dir, 'bot.log')
utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8') 
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s - %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(utf8_stdout),
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'bot.log'),
            encoding='utf-8' # <--- encoding='utf-8' 명시적 추가
        )
    ]
)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

class DiscordHandler(logging.Handler):
    """
    로깅 메시지를 Discord 웹훅으로 보내는 커스텀 핸들러.
    별도의 스레드와 큐를 사용하여 메시지 전송을 비동기적으로 처리합니다.
    """
    def __init__(self):
        super().__init__()
        self.message_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._process_messages())

    async def _process_messages(self):
        while not self.stop_event.is_set() or not self.message_queue.empty():
            try:
                record = self.message_queue.get(timeout=1)
                await self._send_discord_message_async(record)
                self.message_queue.task_done()
            except queue.Empty:
                continue

    def emit(self, record):
        if not DISCORD_WEBHOOK_URL:
            return
        self.message_queue.put(record)

    async def _send_discord_message_async(self, message):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(DISCORD_WEBHOOK_URL, json=message) as response:
                    if response.status != 204:
                        response_text = await response.text()
                        get_logger("DiscordHandler").error(f"Failed to send Discord message: Status {response.status}, Response: {response_text}")
        except aiohttp.ClientError as e:
            get_logger("DiscordHandler").error(f"Aiohttp client error sending Discord message: {e}")
        except Exception as e:
            get_logger("DiscordHandler").error(f"Unexpected error in _send_discord_message_async: {e}")




    def stop(self):
        self.stop_event.set()
        self.thread.join()
        self.loop.stop()

# Discord 핸들러를 추가하려면 주석을 해제하세요.
discord_handler = DiscordHandler()
discord_handler.setLevel(logging.ERROR)
# Discord에는 오류 메시지만 보냅니다.
get_logger("BinanceBot").addHandler(discord_handler)


# msg.py 하단에 추가

async def send_discord_notification(title, message, color=0x3498db):
    """
    STELA 전용 디스코드 Embed 메시지 전송 함수
    color 예시: 파랑(0x3498db), 초록(0x2ecc71), 빨강(0xe74c3c)
    """
    if not DISCORD_WEBHOOK_URL or not getattr(settings, 'ENABLE_DISCORD_ALERTS', True):
        return

    payload = {
        "embeds": [{
            "title": f"{title}", # 🚀 STELA - 
            "description": message,
            "color": color,
            # "footer": {"text": "STELA Intelligent Trading System"}
        }]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(DISCORD_WEBHOOK_URL, json=payload) as response:
                if response.status not in [200, 204]:
                    print(f"디스코드 전송 실패: {response.status}")
    except Exception as e:
        print(f"디스코드 에러: {e}")

# 다른 파일에서 동기 방식으로 편하게 부를 수 있게 래퍼 함수 추가
# src/shared/msg.py 파일 수정

# src/shared/msg.py

def stela_msg(title, message, color:MsgColorCode):
    """
    모든 스레드에서 호출 가능한 가장 안전한 방식입니다.
    비동기 루프를 직접 건드리지 않고 DiscordHandler의 큐에 데이터를 넣습니다.
    """
    if not DISCORD_WEBHOOK_URL:
        return

    # 전송할 데이터 구조 생성
    payload = {
        "embeds": [{
            "title": f"{title}",
            "description": message,
            "color": color.value,
        }]
    }
    
    # DiscordHandler의 내부 큐에 payload를 직접 삽입 (동기 방식이라 즉각 반응)
    discord_handler.message_queue.put(payload)

# def send_order_buy_msg(symbol, side, entry, amount, color):
#     if side == "LONG":
#         icon = '🟢'
#         side_text = "Long"
#     else:
#         icon = "🔴"
#         side_text = "Short"

#     if percent > 0:
#         precent_prefix = '+'
#     elif percent < 0:
#         precent_prefix = '-'
#     else:
#         precent_prefix = ""

#     if amount > 0:
#         amount_prefix = '+'
#     elif amount < 0:
#         amount_prefix = '-'
#     else:
#         amount_prefix = ""

#     pct_text = f" entry{percent}%"
#     pct_text = f" {precent_prefix}{percent}%"
#     amt_text = f"{amount_prefix}{amount} {app_config.FUTURES_TRADING_ASSET}"
#     content = f"{pct_text}{amt_text:>{28 - len(pct_text)}}"
#     stela_msg(
#         f"{icon}  [Close {side_text}]  {symbol}", 
#         f"**`{content}`**", 
#         color
#     )


def send_order_sell_msg(symbol:str, side:PositionSide, amount):
    match side:
        case PositionSide.LONG:
            side_text = "Long"
        case PositionSide.SHORT:
            side_text = "Short"

    if amount > 0:
        amount_prefix = '+'
        color = MsgColorCode.GREEN
    elif amount < 0:
        amount_prefix = '-'
        color = MsgColorCode.RED
    else:
        amount_prefix = ""
        color = MsgColorCode.GRAY

    content = f"{amount_prefix}{abs(amount):.2f} {app_config.FUTURES_TRADING_ASSET}"

    stela_msg(
        f"[{symbol}]  {side_text}  Closed", 
        f"**`{content}`**", 
        color
    )

def send_bnb_recharge_msg(usdt_amount, bnb_amount, new_days):
    """
    BNB 자동 충전 완료 알림 (영문)
    """
    content = (
        f"Low fee balance detected (under 2 days).\n"
        f"System has automatically replenished 7 days of BNB.\n\n"
        f"**• Transferred :** `{usdt_amount:.2f} USDT`\n"
        f"**• Purchased   :** `{bnb_amount:.4f} BNB`\n"
        f"**• New Survival:** `{new_days:.2f} Days`"
    )
    
    stela_msg(
        title="⚠️ BNB AUTO-RECHARGE EXECUTED",
        message=content,
        color=MsgColorCode.GREEN  # 성공적인 조치이므로 녹색 권장
    )