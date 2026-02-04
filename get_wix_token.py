import requests

data = {
    'grant_type': 'authorization_code',
    'client_id': 'fa1b2d0c-1211-4491-9abb-596200052dac',
    'client_secret': '77af01cb-3877-40bf-a66d-4e93fa9069ae',
    'code': 'OAUTH2.eyJraWQiOiJWUTQwMVRlWiIsImFsZyI6IkhTMjU2In0.eyJkYXRhIjoie1wiYXBwSWRcIjpcImZhMWIyZDBjLTEyMTEtNDQ5MS05YWJiLTU5NjIwMDA1MmRhY1wiLFwiaW5zdGFuY2VJZFwiOlwiYzM3YmU3NjAtMTVmYS00OGI0LWIzOWItNDZkNDA2ZWI2YmE4XCIsXCJzY29wZVwiOltdLFwidmVyc2lvblwiOlwiMS4wLjBcIn0iLCJpYXQiOjE3NzAxOTAxNDUsImV4cCI6MTc3MDE5MDc0NX0.6JkBaE7TKYvFTX0Gb6AAKO48gbBaoyfDkbfQtl_9Fk8'
}

try:
    response = requests.post('https://www.wixapis.com/oauth/access', json=data, timeout=30)
    print('Status:', response.status_code)
    print('Response:', response.text)
except Exception as e:
    print('Error:', str(e))
