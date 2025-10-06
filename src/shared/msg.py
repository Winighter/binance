import logging
import os
import asyncio
import aiohttp
import settings
import threading
import queue
import io 
import sys

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
        if not settings.DISCORD_WEBHOOK_URL:
            return
        self.message_queue.put(record)

    async def _send_discord_message_async(self, message):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(settings.DISCORD_WEBHOOK_URL, json=message) as response:
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