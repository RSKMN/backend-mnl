import httpx
BASE_URL = 'http://127.0.0.1:8001/api/v1'
res = httpx.post(f'{BASE_URL}/auth/login', json={'email': 'smoke_user3@example.com', 'password': 'Password123!'})
token = res.json()['data']['access_token']
headers = {'Authorization': f'Bearer {token}'}
res_a = httpx.get(f'{BASE_URL}/projects/6a215a28d4e4b44c3f1f4044/docking/results', headers=headers)
print('Run A:', res_a.json()['data']['items'][0] if res_a.json()['data']['items'] else 'None')
res_b = httpx.get(f'{BASE_URL}/projects/6a215a64d4e4b44c3f1f4080/docking/results', headers=headers)
print('Run B:', res_b.json()['data']['items'][0] if res_b.json()['data']['items'] else 'None')
