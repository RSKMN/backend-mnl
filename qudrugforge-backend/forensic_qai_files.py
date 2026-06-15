import os
run_dir = r"E:\rskmn\Npersonal\quinfosys\drug_discovery_research\work\mnl\q-ai-drug-new\outputs\runs\6a2fd8aff9e4ec7b892576b9"

for root, dirs, files in os.walk(run_dir):
    for f in files:
        print(os.path.join(root, f).replace(run_dir, ""))
