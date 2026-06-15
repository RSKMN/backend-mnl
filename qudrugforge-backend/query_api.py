import requests
import json

base_url = "https://decide-lafayette-quoted-advocate.trycloudflare.com"

# First login
login_res = requests.post(f"{base_url}/api/v1/auth/login", json={
    "email": "test_user_1781516635699@quinfosys.com",
    "password": "Password123!"
})
token = login_res.json().get('access_token') or login_res.json().get('data', {}).get('access_token')

headers = {"Authorization": f"Bearer {token}"}
project_id = "6a2fc96160689a672c937aed"

endpoints = [
    f"/api/v1/projects/{project_id}/docking/results",
    f"/api/v1/projects/{project_id}/gnina/results",
    f"/api/v1/projects/{project_id}/molecules",
    f"/api/v1/projects/{project_id}/validation?panel=admet",
    f"/api/v1/projects/{project_id}/reports"
]

for ep in endpoints:
    url = f"{base_url}{ep}"
    res = requests.get(url, headers=headers)
    print(f"=== {ep} ===")
    if res.status_code == 200:
        data = res.json()
        items = data.get('data', {}).get('items', [])
        if not items and 'items' in data:
            items = data['items']
        elif not items and isinstance(data.get('data'), list):
            items = data['data']
        print(f"Count: {len(items)}")
        if items:
            print(f"Sample: {json.dumps(items[0], indent=2)[:500]}")
    else:
        print(f"Failed: {res.status_code}")
    print("\n")
