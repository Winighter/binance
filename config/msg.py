import datetime, requests, time

url = 'https://discord.com/api/webhooks/'

class Message():

    def __init__(self, _msg):

        now = datetime.datetime.now()
        message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {str(_msg)}"}
        requests.post(url, data=message)
        print(message)
