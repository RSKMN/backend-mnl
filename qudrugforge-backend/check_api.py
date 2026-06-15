import re

path = r"E:\rskmn\Npersonal\quinfosys\drug_discovery_research\work\mnl\q-ai-drug-new\src\q_ai_drug\service\api.py"
with open(path, "r", encoding="utf-8") as f:
    for line in f:
        if "@app.post" in line or "research" in line:
            print(line.strip())
