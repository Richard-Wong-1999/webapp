import requests

data = {
    'grant_type': 'authorization_code',
    'client_id': 'fa1b2d0c-1211-4491-9abb-596200052dac',
    'client_secret': '77af01cb-3877-40bf-a66d-4e93fa9069ae',
    'code': 'OAUTH2.eyJraWQiOiJWUTQwMVRlWiIsImFsZyI6IkhTMjU2In0.eyJkYXRhIjoie1wiYXBwSWRcIjpcImZhMWIyZDBjLTEyMTEtNDQ5MS05YWJiLTU5NjIwMDA1MmRhY1wiLFwiaW5zdGFuY2VJZFwiOlwiZDVlYWNiMTUtZDI4YS00NWJjLTk2ZTMtZjViMDAxOTkyNjQ2XCIsXCJzY29wZVwiOltdLFwidmVyc2lvblwiOlwiMS4wLjBcIn0iLCJpYXQiOjE3NzAxODcyNjMsImV4cCI6MTc3MDE4Nzg2M30.oM-9MI9tvogBQoxFj21WDnOQ8L9kmu6lV1mBmm1YQgs'
}

try:
    response = requests.post('https://www.wixapis.com/oauth/access', json=data, timeout=30)
    print('Status:', response.status_code)
    print('Response:', response.text)
except Exception as e:
    print('Error:', str(e))
