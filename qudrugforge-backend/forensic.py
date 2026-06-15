import os

backend_dir = r"E:\rskmn\Npersonal\quinfosys\drug_discovery_research\work\mnl\backend-mnl\qudrugforge-backend"
logs = ["backend.log", "celery.log"]
project_id = "6a2fc96160689a672c937aed"

for log_file in logs:
    path = os.path.join(backend_dir, log_file)
    if os.path.exists(path):
        print(f"--- Matches in {log_file} ---")
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if any(x in line for x in ["6a2fcb0c", "6a2fcf9c", "6a2fd74d", "6a2fd8af"]):
                    print(line.strip())
