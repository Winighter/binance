# msg.py (또는 더 나은 분리를 위해 logging_config.py 라는 새 파일 생성)
import logging
import os
import requests # Discord 웹훅을 여전히 사용하려면 필요합니다.
import config.config as app_config # Discord 웹훅 URL을 위해 필요합니다.

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
            requests.post(app_config.DISCORD_WEBHOOK_URL, json=message) # json=message로 변경
        except Exception:
            self.handleError(record)

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