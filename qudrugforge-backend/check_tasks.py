import os

tasks_file = r"E:\rskmn\Npersonal\quinfosys\drug_discovery_research\work\mnl\backend-mnl\qudrugforge-backend\app\services\tasks.py"
with open(tasks_file, "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if "start" in line or "requests.post" in line or "api/v1" in line or "research" in line:
            print(f"{i+1}: {line.strip()}")
