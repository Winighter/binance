import datetime, requests

url = 'https://discord.com/api/webhooks/1349690403829448725/7snHkoLZftpXa58O1KVS1NzhUoN9hBm2QUIwxAMcTFIHkEESIO8uHS-yFk3QPuqNcpPq'

class Message():

    def __init__(self, _msg):

        now = datetime.datetime.now()
        message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {str(_msg)}"}
        requests.post(url, data=message)
        print(message)
