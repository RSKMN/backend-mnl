import httpx
import sys
import subprocess
import time

BASE_URL = "http://127.0.0.1:8001/api/v1"

def run_validation(run_name, center_x):
    print(f"\n--- Starting {run_name} ---")
    
    # 1. Login
    res = httpx.post(f"{BASE_URL}/auth/login", json={
        "email": "smoke_user@example.com",
        "password": "Password123!"
    })
    
    if res.status_code != 200:
        # Register if not exists
        res = httpx.post(f"{BASE_URL}/auth/register", json={
            "email": "smoke_user@example.com",
            "password": "Password123!",
            "full_name": "Smoke Investigator",
            "workspace_name": "Smoke Research Lab"
        }, timeout=120.0)
        if res.status_code != 200:
            print("Failed to register/login")
            sys.exit(1)
            
    token = res.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # Get workspace
    res_me = httpx.get(f"{BASE_URL}/auth/me", headers=headers)
    workspace_id = res_me.json()["data"]["workspaces"][0]["id"]
    
    # 2. Create Project
    res_proj = httpx.post(f"{BASE_URL}/projects", json={
        "workspace_id": workspace_id,
        "name": f"Validation Project {run_name}",
        "description": "Verification EGFR simulation run",
        "disease_type": "Cancer",
        "cancer_type": "NSCLC"
    }, headers=headers)
    project_id = res_proj.json()["data"]["id"]
    print(f"Created project {project_id}")
    
    # 2.5 Upload Receptor File
    file_path = "1CRN.pdb"
    with open(file_path, "rb") as f:
        res_upload = httpx.post(f"{BASE_URL}/projects/{project_id}/files/upload", files={"file": f}, data={"category": "protein_structure", "description": "1CRN Receptor"}, headers=headers)
    print(f"Upload file status: {res_upload.status_code}")
    if res_upload.status_code != 200:
        print(f"Failed to upload: {res_upload.text}")
        sys.exit(1)
    file_id = res_upload.json()["data"]["file"]["file_id"]
    
    # Assign it
    res_assign = httpx.patch(f"{BASE_URL}/projects/{project_id}/inputs/files", json={
        "protein_structure_file_id": file_id
    }, headers=headers)
    print(f"Assigned file. Status: {res_assign.status_code}")
    
    # 3. Update Inputs (Binding Site)
    res_input = httpx.patch(f"{BASE_URL}/projects/{project_id}/inputs/binding-site", json={
        "mode": "box",
        "box": {
            "center_x": center_x,
            "center_y": 10.0,
            "center_z": 10.0,
            "size_x": 20.0,
            "size_y": 20.0,
            "size_z": 20.0
        }
    }, headers=headers)
    print(f"Updated binding site. Status: {res_input.status_code}")
    
    # 4. Trigger Pipeline (Synchronously wait for completion if possible, but actually it returns pipeline_run_id)
    # The current implementation runs supervisor DAG synchronously or async? 
    # run_pipeline_supervisor is run via Celery usually, wait, is Celery running?
    # If ENABLE_DEV_JOB_SIMULATION is true, it might be simulated, but we modified the code to support real sync.
    res_run = httpx.post(f"{BASE_URL}/projects/{project_id}/pipeline/run", json={
        "pipeline": ["target_ranking", "molecule_generation", "docking"],
        "parameters": {}
    }, headers=headers, timeout=300.0)
    print(f"Pipeline triggered. Status: {res_run.status_code}")
    
    if res_run.status_code != 200:
        print(f"Failed to run pipeline: {res_run.text}")
        sys.exit(1)
        
    pipeline_run_id = res_run.json()["data"]["pipeline_run_id"]
    
    # Poll for completion
    completed = False
    for i in range(100):
        time.sleep(2)
        res_poll = httpx.get(f"{BASE_URL}/projects/{project_id}/pipeline/runs/{pipeline_run_id}", headers=headers)
        if res_poll.status_code != 200:
            print(f"Poll error: {res_poll.text}")
            continue
        status = res_poll.json()["data"]["status"]
        print(f"Pipeline status: {status}")
        if status in ["completed", "failed"]:
            completed = True
            break
            
    if not completed:
        print("Pipeline didn't complete in time.")
        sys.exit(1)
        
    # 5. Fetch Docking Results
    res_dock = httpx.get(f"{BASE_URL}/projects/{project_id}/docking/results", headers=headers)
    results = res_dock.json()["data"]["items"]
    print(f"Total docking results: {len(results)}")
    
    if len(results) > 0:
        # Print affinity of first result to see if they differ
        print(f"First result: {results[0]}")
        print(f"First result affinity: {results[0].get('score', 'N/A')}")
        
    return results

if __name__ == "__main__":
    # Start Backend
    print("Starting backend...")
    backend = subprocess.Popen([r".venv\Scripts\python", "-m", "uvicorn", "app.main:app", "--port", "8001", "--host", "127.0.0.1"])
    time.sleep(5)
    
    try:
        results_A = run_validation("Run A", 5.0)
        results_B = run_validation("Run B", -5.0)
        
        # Compare
        if len(results_A) > 0 and len(results_B) > 0:
            score_A = results_A[0].get('score')
            score_B = results_B[0].get('score')
            
            print("\n=== Validation Results ===")
            print(f"Run A Affinity: {score_A}")
            print(f"Run B Affinity: {score_B}")
            
            if score_A != score_B:
                print("SUCCESS: Dynamic results differ based on coordinates!")
            else:
                print("FAILED: Results are identical. Caching or hardcoding issue?")
        else:
            print("FAILED: No docking results imported.")
    finally:
        backend.terminate()
