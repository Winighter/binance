import logging
import os
import asyncio
import aiohttp
import settings

# 기본 로거를 설정합니다.
# 다른 모듈에서 'name'을 인수로 받아 새로운 로거를 생성하므로,
# 기본 로거의 설정만 여기서 정의합니다.
log_dir = os.path.join(os.path.dirname(__file__), '...')
log_file_path = os.path.join(log_dir, 'bot.log')

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s - %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'bot.log'))
    ]
)

def get_logger(name: str) -> logging.Logger:
    """
    주어진 이름으로 로거 인스턴스를 가져옵니다.
    로거가 이미 존재하면 기존 로거를 반환합니다.
    """
    return logging.getLogger(name)

# Discord 웹훅 URL이 config.py에 정의되어 있다고 가정합니다.
class DiscordHandler(logging.Handler):
    """
    로깅 메시지를 Discord 웹훅으로 보내는 커스텀 핸들러.
    """
    def emit(self, record):
        if not settings.DISCORD_WEBHOOK_URL:
            return

        message = {
            "content": f"[{record.levelname}] {record.name}: {self.format(record)}"
        }

        asyncio.run(self._send_discord_message_async(message))

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

# Discord 핸들러를 추가하려면 주석을 해제하세요.
discord_handler = DiscordHandler()
discord_handler.setLevel(logging.ERROR)
# Discord에는 오류 메시지만 보냅니다.
get_logger("BinanceBot").addHandler(discord_handler)