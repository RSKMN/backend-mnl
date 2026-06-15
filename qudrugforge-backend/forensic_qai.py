import os
import sys

run_dir = r"E:\rskmn\Npersonal\quinfosys\drug_discovery_research\work\mnl\q-ai-drug-new\outputs\runs\6a2fd8aff9e4ec7b892576b9"

if not os.path.exists(run_dir):
    print(f"Run dir does not exist: {run_dir}")
    sys.exit()

print(f"Walking {run_dir}...\n")
for root, dirs, files in os.walk(run_dir):
    for name in files:
        path = os.path.join(root, name)
        size = os.path.getsize(path)
        ctime = os.path.getctime(path)
        print(f"FILE: {path} | Size: {size} | CTime: {ctime}")
        if "csv" in name.lower() or "pdbqt" in name.lower() or "json" in name.lower() or "log" in name.lower():
            print("--- First 20 lines ---")
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f):
                        print(line.strip())
                        if i >= 19:
                            break
            except Exception as e:
                print(f"Could not read: {e}")
            print("----------------------\n")
