import os
import sys
import httpx

# Read backend URL from environment or default to local development port 8001
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8001/api/v1")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3001")

def run_seed():
    print("====================================================")
    print("  QuDrugForge Phase 17 Local Demo Seeding Script")
    print("====================================================")
    print(f"Targeting Backend API: {BACKEND_URL}")
    print(f"Targeting Frontend URL: {FRONTEND_URL}")
    
    # 1. Register/Login Demo User
    email = "demo.investigator@example.com"
    password = "DemoPassword123!"
    
    headers = {}
    token = None
    workspace = None
    
    print("\n1. Authentication Step...")
    try:
        # Try registering
        res = httpx.post(f"{BACKEND_URL}/auth/register", json={
            "email": email,
            "password": password,
            "full_name": "Demo Investigator",
            "workspace_name": "Primary Demo Lab"
        }, timeout=10.0)
        
        if res.status_code == 200:
            print("[OK] Successfully registered a fresh demo user!")
            reg_data = res.json()["data"]
            token = reg_data["access_token"]
            workspace = reg_data["workspace"]
        else:
            # Already exists, try logging in
            print("User already exists. Logging in with existing credentials...")
            login_res = httpx.post(f"{BACKEND_URL}/auth/login", json={
                "email": email,
                "password": password
            }, timeout=10.0)
            
            if login_res.status_code != 200:
                print(f"[ERROR] Failed to login: {login_res.status_code} - {login_res.text}")
                sys.exit(1)
            
            print("[OK] Successfully logged in!")
            token = login_res.json()["data"]["access_token"]
            
            # Fetch me to get workspaces
            headers = {"Authorization": f"Bearer {token}"}
            me_res = httpx.get(f"{BACKEND_URL}/auth/me", headers=headers)
            workspace = me_res.json()["data"]["workspaces"][0]
            
    except Exception as e:
        print(f"[ERROR] Failed to connect to Backend Server. Please make sure it is running at {BACKEND_URL}")
        print(f"Error detail: {e}")
        sys.exit(1)
        
    headers = {"Authorization": f"Bearer {token}"}
    workspace_id = workspace["id"]
    print(f"  Active Workspace: {workspace['name']} ({workspace_id})")
    
    # 2. Get or Create Project
    print("\n2. Project Setup Step...")
    project_name = "EGFR NSCLC Discovery Program"
    project_id = None
    
    # Check if project already exists
    projects_res = httpx.get(f"{BACKEND_URL}/projects", headers=headers)
    if projects_res.status_code == 200:
        projects = projects_res.json()["data"]
        for p in projects:
            if p["name"] == project_name:
                project_id = p["id"]
                print(f"[OK] Found existing project: '{project_name}' ({project_id})")
                break
                
    if not project_id:
        print(f"Creating new project '{project_name}'...")
        proj_res = httpx.post(f"{BACKEND_URL}/projects", json={
            "workspace_id": workspace_id,
            "name": project_name,
            "description": "Accelerating EGFR T790M inhibitor synthesis and testing",
            "disease_type": "Oncology",
            "cancer_type": "Lung Cancer"
        }, headers=headers)
        
        if proj_res.status_code != 200:
            print(f"[ERROR] Failed to create project: {proj_res.status_code} - {proj_res.text}")
            sys.exit(1)
            
        project_id = proj_res.json()["data"]["id"]
        print(f"[OK] Project created successfully! ID: {project_id}")
        
    # 3. Upload files if not present
    print("\n3. Uploading Sample Target/Library Files...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, "..", "tests", "utils", "sample_files", "ligands.csv")
    pdb_path = os.path.join(script_dir, "..", "tests", "utils", "sample_files", "protein.pdb")
    
    if not os.path.exists(csv_path) or not os.path.exists(pdb_path):
        print("[ERROR] Sample PDB/CSV files could not be found under tests/utils/sample_files/.")
        sys.exit(1)
        
    # Check uploaded files first to prevent duplicate files
    files_res = httpx.get(f"{BACKEND_URL}/projects/{project_id}/files", headers=headers)
    files = files_res.json()["data"]["items"] if files_res.status_code == 200 else []
    
    csv_file = next((f for f in files if f["original_filename"] == "ligands.csv"), None)
    pdb_file = next((f for f in files if f["original_filename"] == "protein.pdb"), None)
    
    if not csv_file:
        print("Uploading ligands.csv compound library...")
        with open(csv_path, "rb") as f:
            res_csv = httpx.post(
                f"{BACKEND_URL}/projects/{project_id}/files/upload",
                files={"file": ("ligands.csv", f, "text/csv")},
                data={"file_type": "compound_library", "source_module": "project_inputs"},
                headers=headers
            )
        csv_file = res_csv.json()["data"]["file"]
        print("[OK] Uploaded ligands.csv successfully!")
    else:
        print(f"[OK] ligands.csv already exists. File ID: {csv_file['file_id']}")
        
    if not pdb_file:
        print("Uploading protein.pdb structural receptor...")
        with open(pdb_path, "rb") as f:
            res_pdb = httpx.post(
                f"{BACKEND_URL}/projects/{project_id}/files/upload",
                files={"file": ("protein.pdb", f, "application/octet-stream")},
                data={"file_type": "protein_structure", "source_module": "project_inputs"},
                headers=headers
            )
        pdb_file = res_pdb.json()["data"]["file"]
        print("[OK] Uploaded protein.pdb successfully!")
    else:
        print(f"[OK] protein.pdb already exists. File ID: {pdb_file['file_id']}")
        
    # 4. Set inputs
    print("\n4. Configuring Project Inputs...")
    httpx.patch(
        f"{BACKEND_URL}/projects/{project_id}/inputs/binding-site",
        json={
            "mode": "box",
            "box": {
                "center_x": 10.0,
                "center_y": 10.0,
                "center_z": 10.0,
                "size_x": 20.0,
                "size_y": 20.0,
                "size_z": 20.0
            }
        },
        headers=headers
    )
    print("[OK] Binding site bounding box updated successfully!")
    
    # 5. Import Molecules
    print("\n5. Importing SMILES Candidates...")
    mols_res = httpx.get(f"{BACKEND_URL}/projects/{project_id}/molecules", headers=headers)
    mols_count = mols_res.json()["data"]["total"] if mols_res.status_code == 200 else 0
    
    if mols_count == 0:
        print("Triggering molecular candidates import...")
        httpx.post(
            f"{BACKEND_URL}/projects/{project_id}/molecules/import",
            json={
                "source_file_id": csv_file["file_id"],
                "smiles_column": "canonical_smiles",
                "compound_id_column": "compound_id"
            },
            headers=headers
        )
        print("[OK] Successfully imported 5 candidates!")
    else:
        print(f"[OK] Candidates already present. Count: {mols_count}")
        
    # 6. Create Target
    print("\n6. Configuring Targets...")
    target_res = httpx.get(f"{BACKEND_URL}/projects/{project_id}/targets", headers=headers)
    targets_list = target_res.json()["data"]["items"] if target_res.status_code == 200 else []
    
    if len(targets_list) == 0:
        print("Configuring EGFR Target...")
        httpx.post(
            f"{BACKEND_URL}/projects/{project_id}/targets",
            json={
                "gene": "EGFR",
                "uniprot_id": "P00533",
                "protein_name": "Epidermal growth factor receptor",
                "structure_file_id": pdb_file["file_id"],
                "rank_score": 0.90,
                "status": "candidate"
            },
            headers=headers
        )
        print("[OK] Target EGFR created!")
    else:
        print(f"[OK] Targets already configured. Count: {len(targets_list)}")
        
    # 7. Create/Get Report
    print("\n7. Compiling Preclinical Discovery Report...")
    report_res = httpx.get(f"{BACKEND_URL}/projects/{project_id}/reports", headers=headers)
    reports = report_res.json()["data"]["reports"] if report_res.status_code == 200 else []
    
    report_id = None
    if len(reports) > 0:
        report_id = reports[0]["report_id"]
        print(f"[OK] Report draft already exists: {report_id}")
    else:
        print("Creating Preclinical Screening Report Draft...")
        rep_create = httpx.post(
            f"{BACKEND_URL}/projects/{project_id}/reports",
            json={
                "title": "Oncology EGFR Blockade Summary",
                "report_type": "project_summary"
            },
            headers=headers
        )
        report_id = rep_create.json()["data"]["report_id"]
        print(f"[OK] Created Report Draft! ID: {report_id}")
        
        # Trigger report compilation
        print("Compiling PDF/CSV/HTML files...")
        httpx.post(
            f"{BACKEND_URL}/projects/{project_id}/reports/{report_id}/generate",
            json={
                "formats": ["csv", "html", "pdf"],
                "include_sections": ["molecules", "docking", "gnina", "quantum", "admet", "simulations"],
                "top_n": 5
            },
            headers=headers
        )
        print("[OK] Files compiled successfully!")
        
    # Fetch report files
    files_list_res = httpx.get(f"{BACKEND_URL}/projects/{project_id}/reports/{report_id}/files", headers=headers)
    rep_files = files_list_res.json()["data"]["files"] if files_list_res.status_code == 200 else []
    file_ids = [rf["file_id"] for rf in rep_files]
    
    # 8. Print Seeding Accomplishments
    print("\n==============================================")
    print("  SEEDING PROCESS COMPLETED SUCCESSFULLY!")
    print("==============================================")
    print(f"Demo User Credentials :  Email: {email} | Password: {password}")
    print(f"Authorization Note    :  Send bearer JWT in Authorization header for APIs")
    print(f"Workspace ID          :  {workspace_id}")
    print(f"Project ID            :  {project_id}")
    print(f"Report ID             :  {report_id}")
    print(f"Generated File IDs    :  {', '.join(file_ids) if file_ids else 'None'}")
    print("----------------------------------------------")
    print(f"--> Direct URL to Open :  {FRONTEND_URL}/login")
    print("==============================================")

if __name__ == "__main__":
    run_seed()
