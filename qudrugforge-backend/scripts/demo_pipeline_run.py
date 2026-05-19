#!/usr/bin/env python
import os
import sys
import asyncio
from bson import ObjectId

# Set PYTHONPATH to include the parent folder
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.database import connect_to_mongo as init_db, close_mongo_connection as close_db
from app.services.pipeline_orchestrator_service import pipeline_orchestrator_service
from app.repositories.project_repository import project_repository
from app.repositories.pipeline_repository import pipeline_repository
from app.repositories.workspace_repository import workspace_repository
from app.utils.datetime import utc_now

async def run_demo():
    print("======================================================================")
    print("           QuDrugForge™ Pipeline Orchestration Demo Validation        ")
    print("======================================================================")
    print("Initializing MongoDB connection pool...")
    await init_db()

    try:
        # 1. Fetch or create a default demo project
        print("\n[1/6] Resolving oncology research program...")
        projects = await project_repository.collection.find().to_list(length=1)
        
        # Get a fallback user from the DB if available, or create one
        from app.repositories.user_repository import user_repository
        users = await user_repository.collection.find().to_list(length=1)
        if users:
            user_id = str(users[0]["_id"])
        else:
            u_id = ObjectId()
            await user_repository.collection.insert_one({
                "_id": u_id,
                "email": "demo_member@quinfosys.com",
                "full_name": "Demo Member",
                "hashed_password": "dummy",
                "status": "active"
            })
            user_id = str(u_id)

        if projects:
            project = projects[0]
            print(f"-> Found existing project: '{project['name']}' (ID: {project['_id']})")
            workspace_id = str(project["workspace_id"])
            
            # Ensure membership
            member = await workspace_repository.members_collection.find_one({
                "workspace_id": ObjectId(workspace_id),
                "user_id": ObjectId(user_id)
            })
            if not member:
                await workspace_repository.members_collection.insert_one({
                    "workspace_id": ObjectId(workspace_id),
                    "user_id": ObjectId(user_id),
                    "role": "owner",
                    "status": "active",
                    "joined_at": utc_now()
                })
        else:
            # Create a mock workspace
            w_id = ObjectId()
            await workspace_repository.collection.insert_one({
                "_id": w_id,
                "name": "Oncology Research Workspace",
                "slug": "oncology-research",
                "created_at": utc_now()
            })
            # Insert workspace member
            await workspace_repository.members_collection.insert_one({
                "workspace_id": w_id,
                "user_id": ObjectId(user_id),
                "role": "owner",
                "status": "active",
                "joined_at": utc_now()
            })
            # Create project
            p_id = ObjectId()
            await project_repository.collection.insert_one({
                "_id": p_id,
                "workspace_id": w_id,
                "name": "EGFR NSCLC Discovery Program",
                "disease_type": "Non-small cell lung cancer",
                "cancer_type": "EGFR",
                "description": "EGFR mutant-selective lead optimization",
                "status": "active",
                "created_at": utc_now()
            })
            project = await project_repository.get_project_by_id(str(p_id))
            print(f"-> Created new demo project: '{project['name']}' (ID: {project['_id']})")

        project_id = str(project["_id"])
        workspace_id = str(project["workspace_id"])

        # 2. Trigger pipeline run enqueuing target stages
        print("\n[2/6] Triggering sequential orchestration pipeline...")
        pipeline_run = await pipeline_orchestrator_service.create_pipeline_run(
            project_id=project_id,
            workspace_id=workspace_id,
            pipeline=["target_ranking", "molecule_generation", "filtering", "docking", "gnina", "quantum", "admet", "simulation", "report"],
            parameters={},
            user_id=user_id
        )
        pipeline_run_id = str(pipeline_run["_id"])
        print(f"-> Created master pipeline run: {pipeline_run_id}")
        print(f"-> Status: '{pipeline_run['status']}'")
        print(f"-> Target stages: {pipeline_run['pipeline']}")

        # 3. Spawn background sequential execution task
        print("\n[3/6] Starting sequential execution adapters...")
        task = asyncio.create_task(
            pipeline_orchestrator_service.run_pipeline(
                pipeline_run_id=pipeline_run_id,
                project_id=project_id,
                user_id=user_id
            )
        )

        # 4. Poll progress and print active stage statuses
        print("\n[4/6] Polling execution progress logs (every 2.5 seconds)...")
        completed = False
        while not completed:
            run_state = await pipeline_repository.get_pipeline_run_by_id(pipeline_run_id)
            if not run_state:
                print("Error: pipeline run state lost.")
                break
            
            status = run_state["status"]
            print(f"\n--- Progress Tick (Status: '{status.upper()}') ---")
            
            for stage, details in run_state.get("stage_statuses", {}).items():
                stage_status = details.get("status", "queued")
                progress = details.get("progress", 0)
                exp_link = f" (Exp ID: {details['experiment_id']})" if details.get("experiment_id") else ""
                print(f"  * {stage:22} : [{stage_status.upper():12}] - Progress: {progress:3}% {exp_link}")

            if status in ("completed", "failed", "cancelled"):
                completed = True
                print(f"\nExecution concluded with state: '{status.upper()}'")
            else:
                await asyncio.sleep(2.5)

        # Wait for task completion
        await task

        # 5. Fetch and print newly generated reports
        print("\n[5/6] Cataloging generated scientific reports in MongoDB...")
        from app.repositories.report_repository import report_repository
        reports_cursor = report_repository.collection.find({"project_id": ObjectId(project_id)})
        reports = await reports_cursor.to_list(length=100)
        
        if reports:
            print(f"-> Found {len(reports)} generated report dossiers:")
            for idx, rep in enumerate(reports):
                print(f"  {idx+1}. '{rep['title']}' [Type: {rep['report_type']}, Status: {rep['status']}]")
        else:
            print("-> No reports registered in MongoDB.")

        # 6. Report downloadable URLs
        print("\n[6/6] Automated artifact download channels:")
        for idx, rep in enumerate(reports):
            pdf_id = rep.get("pdf_file_id")
            html_id = rep.get("html_file_id")
            
            if pdf_id:
                print(f"  * Download PDF : http://127.0.0.1:8001/api/v1/projects/{project_id}/files/download/{pdf_id}")
            if html_id:
                print(f"  * View HTML    : http://127.0.0.1:8001/api/v1/projects/{project_id}/files/download/{html_id}")

    except Exception as e:
         import traceback
         traceback.print_exc()
         print(f"\nDemo validation failed with error: {e}")
    finally:
        print("\nClosing database connection pool...")
        await close_db()
        print("Demo completed successfully!")

if __name__ == "__main__":
    asyncio.run(run_demo())
