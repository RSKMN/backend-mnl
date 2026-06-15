import httpx
import sys

BASE_URL = "http://127.0.0.1:8001/api/v1"

def smoke_test():
    print("Starting QuDrugForge Full-Stack Smoke Test...")
    
    # 1. Register User
    print("1. Registering user 'smoke_user@example.com'...")
    try:
        res = httpx.post(f"{BASE_URL}/auth/register", json={
            "email": "smoke_user@example.com",
            "password": "Password123!",
            "full_name": "Smoke Investigator",
            "workspace_name": "Smoke Research Lab"
        }, timeout=10.0)
    except Exception as e:
        print(f"FAILED to connect to backend: {e}")
        sys.exit(1)
        
    if res.status_code != 200:
        # If user already exists, let's try login
        print(f"Register returned status {res.status_code}. Attempting login instead...")
        res = httpx.post(f"{BASE_URL}/auth/login", json={
            "email": "smoke_user@example.com",
            "password": "Password123!"
        })
        if res.status_code != 200:
            print(f"FAILED: Login also returned {res.status_code}: {res.text}")
            sys.exit(1)
        
        token = res.json()["data"]["access_token"]
        # Fetch me to get workspace
        headers = {"Authorization": f"Bearer {token}"}
        res_me = httpx.get(f"{BASE_URL}/auth/me", headers=headers)
        workspace = res_me.json()["data"]["workspaces"][0]
    else:
        reg_data = res.json()["data"]
        token = reg_data["access_token"]
        workspace = reg_data["workspace"]
        
    print(f"SUCCESS: Logged in. Workspace: {workspace['name']} ({workspace['id']})")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Verify integrations health
    print("2. Verifying integrations health via backend client...")
    res_health = httpx.get(f"{BASE_URL}/integrations/q-ai-drug/health", headers=headers)
    if res_health.status_code != 200:
        print(f"FAILED: Health endpoint returned {res_health.status_code}: {res_health.text}")
        sys.exit(1)
    print(f"SUCCESS: Integration health: {res_health.json()}")
    
    # 3. Create Project
    print("3. Creating new project 'Smoke Cancer Target EGFR'...")
    res_proj = httpx.post(f"{BASE_URL}/projects", json={
        "workspace_id": workspace["id"],
        "name": "Smoke Cancer Target EGFR",
        "description": "Verification EGFR simulation run",
        "disease_type": "Cancer",
        "cancer_type": "NSCLC"
    }, headers=headers)
    if res_proj.status_code != 200:
        print(f"FAILED: Project creation returned {res_proj.status_code}: {res_proj.text}")
        sys.exit(1)
    project = res_proj.json()["data"]
    project_id = project["id"]
    print(f"SUCCESS: Created project {project['name']} with ID: {project_id}")
    
    # 4. Trigger Artifact Import
    print("4. Triggering artifact import for 'cancer_proof_v1'...")
    res_import = httpx.post(f"{BASE_URL}/projects/{project_id}/q-ai-drug/import-artifacts", json={
        "run_name": "cancer_proof_v1"
    }, headers=headers)
    if res_import.status_code != 200:
        print(f"FAILED: Artifact import returned {res_import.status_code}: {res_import.text}")
        sys.exit(1)
    import_data = res_import.json()["data"]
    print(f"SUCCESS: Import completed. Details: {import_data}")
    
    # 5. Verify results are retrievable
    print("5. Verifying imported docking results...")
    res_dock = httpx.get(f"{BASE_URL}/projects/{project_id}/docking/results", headers=headers)
    if res_dock.status_code != 200 or res_dock.json()["data"]["total"] < 2:
        print(f"FAILED: Docking query returned {res_dock.status_code}: {res_dock.text}")
        sys.exit(1)
    print(f"SUCCESS: Found {res_dock.json()['data']['total']} docking results!")
    
    print("6. Verifying imported gnina results...")
    res_gnina = httpx.get(f"{BASE_URL}/projects/{project_id}/gnina/results", headers=headers)
    if res_gnina.status_code != 200 or res_gnina.json()["data"]["total"] < 2:
        print(f"FAILED: GNINA query returned {res_gnina.status_code}: {res_gnina.text}")
        sys.exit(1)
    print(f"SUCCESS: Found {res_gnina.json()['data']['total']} GNINA results!")
    
    print("\n==============================================")
    print("ALL SMOKE TESTS PASSED SUCCESSFULLY!")
    print("Full stack backend <=> compute engine communication is functional.")
    print("==============================================")

if __name__ == "__main__":
    smoke_test()
