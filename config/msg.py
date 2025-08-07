# msg.py (또는 더 나은 분리를 위해 logging_config.py 라는 새 파일 생성)
import logging
import os
# import requests # Discord 웹훅을 여전히 사용하려면 필요합니다.
import config.config as app_config # Discord 웹훅 URL을 위해 필요합니다.
import asyncio
import aiohttp

# 로거 생성
logger = logging.getLogger('BinanceBot')
logger.setLevel(logging.INFO) # 기본 로깅 레벨 설정

# 콘솔 핸들러를 생성하고 레벨을 info로 설정
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

# 포맷터 생성
formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# ch에 포맷터 추가
ch.setFormatter(formatter)

# 로거에 ch 추가
logger.addHandler(ch)

# 선택 사항: 영구적인 로그를 위한 파일 핸들러
log_file_path = os.path.join(os.path.dirname(__file__), 'bot.log')
fh = logging.FileHandler(log_file_path)
fh.setLevel(logging.DEBUG) # 모든 메시지를 파일에 기록
fh.setFormatter(formatter)
logger.addHandler(fh)

# 선택 사항: Discord 핸들러
# Discord 웹훅 URL이 config.py에 정의되어 있다고 가정합니다.
class DiscordHandler(logging.Handler):
    def emit(self, record):
        try:
            log_entry = self.format(record)
            message = {"content": log_entry}

            # 🚨 수정된 부분 시작 🚨
            # 비동기적으로 메시지를 전송합니다.
            # logging.Handler는 동기적으로 동작해야 하므로, asyncio.create_task를 사용하여
            # Discord 웹훅 전송을 비동기 이벤트 루프에 스케줄링합니다.
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._send_discord_message_async(message))
            except RuntimeError:
                # 이벤트 루프가 실행 중이지 않을 경우 (예: 초기화 또는 테스트 시),
                # 동기적으로 처리하거나 경고를 로깅할 수 있습니다.
                # 여기서는 간단히 경고를 로깅하고 비동기 전송을 건너는 것으로 합니다.
                # 실제 봇 운영 환경에서는 대부분 asyncio 루프가 실행 중일 것입니다.
                logger.warning("No running asyncio loop found for Discord webhook. Sending synchronously (not recommended) or skipping.")
                # Fallback to synchronous sending if no loop, but generally not desired for performance
                # requests.post(app_config.DISCORD_WEBHOOK_URL, json=message)
            # 🚨 수정된 부분 끝 🚨
        except Exception:
            self.handleError(record)

    async def _send_discord_message_async(self, message):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(app_config.DISCORD_WEBHOOK_URL, json=message) as response:
                    if response.status != 204:
                        response_text = await response.text()
                        logger.error(f"Failed to send Discord message: Status {response.status}, Response: {response_text}")
            except aiohttp.ClientError as e:
                logger.error(f"Aiohttp client error sending Discord message: {e}")
            except Exception as e:
                logger.error(f"Unexpected error in _send_discord_message_async: {e}")


# Discord 핸들러를 추가하려면 주석을 해제하세요.
discord_handler = DiscordHandler()
discord_handler.setLevel(logging.ERROR) # Discord에는 오류 메시지만 보냄
discord_handler.setFormatter(formatter)
logger.addHandler(discord_handler)

class Message:
    def __init__(self, _msg, level='info'):
        """
        구성된 로거를 사용하여 로그 메시지를 보냅니다.

        Args:
            _msg (str): 메시지 내용.
            level (str): 로깅 레벨 ('debug', 'info', 'warning', 'error', 'critical').
                         기본값은 'info'.
        """
        if level == 'debug':
            logger.debug(_msg)
        elif level == 'info':
            logger.info(_msg)
        elif level == 'warning':
            logger.warning(_msg)
        elif level == 'error':
            logger.error(_msg)
        elif level == 'critical':
            logger.critical(_msg)
        else:
            logger.info(_msg) # 유효하지 않은 레벨이 제공되면 info로 기본 설정