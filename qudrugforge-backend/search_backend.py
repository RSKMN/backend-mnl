import os
import sys

backend_app_dir = r"E:\rskmn\Npersonal\quinfosys\drug_discovery_research\work\mnl\backend-mnl\qudrugforge-backend\app"

print("Searching for 'ethanol_1' or 'import_quantum' or 'cnn_score'...")
for root, dirs, files in os.walk(backend_app_dir):
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            try:
                with open(path, "r", encoding="utf-8") as file:
                    content = file.read()
                    if "ethanol_1" in content or "import_quantum" in content or "cnn_score" in content or "import_docking" in content:
                        print(f"--- Found in {f} ---")
                        lines = content.split('\n')
                        for i, line in enumerate(lines):
                            if "ethanol_1" in line or "import_quantum" in line or "cnn_score" in line or "import_docking" in line:
                                print(f"{i+1}: {line.strip()}")
            except:
                pass
