import httpx
import sys
import subprocess
import time

BASE_URL = "http://127.0.0.1:8001/api/v1"

def run_validation(run_name, ligand_path):
    print(f"\n--- Starting {run_name} ---")
    
    res = httpx.post(f"{BASE_URL}/auth/login", json={"email": "smoke_user7@example.com", "password": "Password123!"})
    if res.status_code != 200:
        res = httpx.post(f"{BASE_URL}/auth/register", json={"email": "smoke_user7@example.com", "password": "Password123!", "full_name": "Smoke Investigator", "workspace_name": "Smoke Research Lab"}, timeout=120.0)
        if res.status_code != 200:
            print("Failed to register/login")
            sys.exit(1)
            
    token = res.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    res_me = httpx.get(f"{BASE_URL}/auth/me", headers=headers)
    workspace_id = res_me.json()["data"]["workspaces"][0]["id"]
    
    res_proj = httpx.post(f"{BASE_URL}/projects", json={"workspace_id": workspace_id, "name": f"Validation Project {run_name}", "description": "Verification Reference Ligand", "disease_type": "Cancer", "cancer_type": "NSCLC"}, headers=headers)
    project_id = res_proj.json()["data"]["id"]
    print(f"Created project {project_id}")
    
    with open(ligand_path, "rb") as f:
        res_upload = httpx.post(f"{BASE_URL}/projects/{project_id}/files/upload", files={"file": f}, data={"category": "reference_ligand", "description": "Reference Ligand"}, headers=headers)
    if res_upload.status_code != 200:
        print(f"Failed to upload: {res_upload.text}")
        sys.exit(1)
    file_id = res_upload.json()["data"]["file"]["file_id"]
    
    res_assign = httpx.patch(f"{BASE_URL}/projects/{project_id}/inputs/files", json={"reference_ligand_file_id": file_id}, headers=headers)
    print(f"Assigned ligand. Status: {res_assign.status_code}")
    
    res_run = httpx.post(f"{BASE_URL}/projects/{project_id}/pipeline/run", json={"pipeline": ["target_ranking", "molecule_generation", "docking"], "parameters": {}}, headers=headers, timeout=300.0)
    print(f"Pipeline triggered. Status: {res_run.status_code}")
    
    pipeline_run_id = res_run.json()["data"]["pipeline_run_id"]
    
    completed = False
    for i in range(100):
        time.sleep(2)
        res_poll = httpx.get(f"{BASE_URL}/projects/{project_id}/pipeline/runs/{pipeline_run_id}", headers=headers)
        if res_poll.status_code != 200: continue
        status = res_poll.json()["data"]["status"]
        if status in ["completed", "failed"]:
            completed = True
            break
            
    res_dock = httpx.get(f"{BASE_URL}/projects/{project_id}/docking/results", headers=headers)
    results = res_dock.json()["data"]["items"]
    print(f"Total docking results: {len(results)}")
    
    return results, results

if __name__ == "__main__":
    print("Starting backend...")
    backend = subprocess.Popen([r".venv\Scripts\python", "-m", "uvicorn", "app.main:app", "--port", "8001", "--host", "127.0.0.1"])
    time.sleep(5)
    try:
        mols_A, dock_A = run_validation("Run A", "gefitinib.smi")
        mols_B, dock_B = run_validation("Run B", "erlotinib.smi")
        
        print("\n=== Validation Results ===")
        smiles_A = {m["smiles"] for m in mols_A}
        smiles_B = {m["smiles"] for m in mols_B}
        print(f"Run A Unique Smiles: {len(smiles_A)}")
        print(f"Run B Unique Smiles: {len(smiles_B)}")
        intersection = smiles_A.intersection(smiles_B)
        print(f"Intersection count: {len(intersection)}")
        if len(intersection) < len(smiles_A):
            print("SUCCESS: Generated molecules differ! Ligand was correctly seeded.")
        else:
            print("FAILED: Molecules are identical. Ligand was ignored.")
    finally:
        backend.terminate()

