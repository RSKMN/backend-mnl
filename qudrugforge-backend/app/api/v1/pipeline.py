import logging
from typing import Optional, List
from fastapi import APIRouter, BackgroundTasks, Body, Depends, Path, Query

from app.core.dependencies import get_current_active_user
from app.core.exceptions import AppException
from app.schemas.pipeline import PipelineRunRequest, PipelineRunResponse
from app.services.pipeline_orchestrator_service import pipeline_orchestrator_service
from app.repositories.pipeline_repository import pipeline_repository
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.core.rate_limit import limiter
from app.core.config import settings
from fastapi import Request
from app.services.pipeline_validation_service import pipeline_validation_service
from app.services.project_input_service import project_input_service

logger = logging.getLogger("qudrugforge-pipeline-api")

router = APIRouter(prefix="/projects/{project_id}/pipeline", tags=["Pipeline Orchestration"])

async def check_project_and_authorize(project_id: str, user_id: str, allowed_roles: List[str] = None):
    project = await project_repository.get_project_by_id(project_id)
    if not project:
        raise AppException(
            status_code=404,
            code="PROJECT_NOT_FOUND",
            message="Project not found."
        )
    workspace_id = str(project["workspace_id"])
    membership = await workspace_repository.get_membership(workspace_id, user_id)
    if not membership:
        raise AppException(
            status_code=403,
            code="WORKSPACE_ACCESS_DENIED",
            message="User does not have active member permissions for this workspace."
        )
        
    if allowed_roles:
        role = membership.get("role", "viewer").upper()
        if role != "OWNER" and role not in allowed_roles:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message=f"Insufficient permissions. Required one of roles: {allowed_roles}"
            )
            
    return project, workspace_id

@router.post("/run", response_model=None)
@limiter.limit(settings.RATE_LIMIT_PIPELINE)
async def trigger_pipeline_run(
    request: Request,
    project_id: str = Path(...),
    body: PipelineRunRequest = Body(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    project, workspace_id = await check_project_and_authorize(project_id, user_id, allowed_roles=["ADMIN", "SCIENTIST"])

    # 0.a Validate scientific inputs
    inputs_doc = await project_input_service.get_project_inputs(project_id, user_id)
    readiness = pipeline_validation_service.evaluate_readiness(inputs_doc)
    pipeline_validation_service.validate_requested_stages(body.pipeline, readiness)

    # 0. Check Queue Quota per-user
    from bson import ObjectId
    from app.core.exceptions import DomainError
    
    active_pipelines = await pipeline_repository.collection.count_documents({
        "created_by": ObjectId(user_id),
        "status": {"$in": ["queued", "running"]}
    })
    
    if active_pipelines >= settings.MAX_ACTIVE_JOBS_PER_USER:
        raise DomainError(
            status_code=429,
            code="QUEUE_QUOTA_EXCEEDED",
            message=f"Queue quota exceeded. You already have {active_pipelines} active pipeline(s). Maximum allowed is {settings.MAX_ACTIVE_JOBS_PER_USER}."
        )

    # 1. Create pipeline run document
    pipeline_run = await pipeline_orchestrator_service.create_pipeline_run(
        project_id=project_id,
        workspace_id=workspace_id,
        pipeline=body.pipeline,
        parameters=body.parameters,
        user_id=user_id
    )
    
    pipeline_run_id = str(pipeline_run["_id"])

    # 2. Create the Supervisor Job Tracking Record
    from app.repositories.job_repository import job_repository
    from app.utils.datetime import utc_now
    job_doc = {
        "project_id": project["_id"],
        "task_type": "pipeline_supervisor",
        "status": "QUEUED",
        "progress": 0,
        "created_at": utc_now()
    }
    supervisor_job = await job_repository.create_job(job_doc)
    supervisor_job_id = str(supervisor_job["_id"])

    # 3. Enqueue the Supervisor Task
    # Synchronous execution for testing
    await pipeline_orchestrator_service.run_pipeline_supervisor(
        pipeline_run_id, project_id, user_id, supervisor_job_id
    )

    return {
        "success": True,
        "data": {
            "job_id": supervisor_job_id,
            "pipeline_run_id": pipeline_run_id,
            "status": "QUEUED"
        },
        "message": "Scientific orchestration pipeline enqueued and started in background."
    }

@router.get("/readiness", response_model=None)
async def get_pipeline_readiness(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    await check_project_and_authorize(project_id, user_id)

    inputs_doc = await project_input_service.get_project_inputs(project_id, user_id)
    readiness = pipeline_validation_service.evaluate_readiness(inputs_doc)

    return {
        "success": True,
        "data": readiness,
        "message": "Pipeline readiness fetched successfully."
    }

@router.get("/runs", response_model=None)
async def list_pipeline_runs(
    project_id: str = Path(...),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    await check_project_and_authorize(project_id, user_id)

    items, total = await pipeline_repository.list_pipeline_runs(
        project_id=project_id,
        status=status,
        skip=offset,
        limit=limit
    )

    serialized_items = [PipelineRunResponse.from_mongo(item).model_dump() for item in items]

    return {
        "success": True,
        "data": {
            "items": serialized_items,
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "Orchestration pipeline runs fetched successfully."
    }

@router.get("/summary", response_model=None)
async def get_pipeline_summary(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    project, _ = await check_project_and_authorize(project_id, user_id)

    # 1. Fetch latest pipeline run
    runs, _ = await pipeline_repository.list_pipeline_runs(
        project_id=project_id,
        limit=1
    )
    latest_run = PipelineRunResponse.from_mongo(runs[0]).model_dump() if runs else None

    # 2. Query actual imported counts in MongoDB for this project
    from bson import ObjectId
    from app.repositories.molecule_repository import molecule_repository
    from app.repositories.docking_result_repository import docking_result_repository
    from app.repositories.gnina_result_repository import gnina_result_repository
    from app.repositories.quantum_result_repository import quantum_result_repository
    from app.repositories.simulation_result_repository import simulation_result_repository
    from app.repositories.admet_result_repository import admet_result_repository
    from app.repositories.report_repository import report_repository
    from app.integrations.q_ai_drug_execution import q_ai_drug_execution_service
    from app.core.config import settings

    pid_obj = ObjectId(project_id)
    molecules_count = await molecule_repository.collection.count_documents({"project_id": pid_obj})
    docking_count = await docking_result_repository.collection.count_documents({"project_id": pid_obj})
    gnina_count = await gnina_result_repository.collection.count_documents({"project_id": pid_obj})
    quantum_count = await quantum_result_repository.collection.count_documents({"project_id": pid_obj})
    simulation_count = await simulation_result_repository.collection.count_documents({"project_id": pid_obj})
    admet_count = await admet_result_repository.collection.count_documents({"project_id": pid_obj})
    
    reports_cursor = report_repository.collection.find({"project_id": pid_obj})
    reports_docs = await reports_cursor.to_list(length=100)
    
    # Serialize reports
    serialized_reports = []
    for rep in reports_docs:
        serialized_reports.append({
            "report_id": rep.get("report_id"),
            "title": rep.get("title"),
            "report_type": rep.get("report_type"),
            "pdf_file_id": rep.get("pdf_file_id"),
            "html_file_id": rep.get("html_file_id"),
            "status": rep.get("status"),
            "created_at": rep.get("created_at").isoformat() if rep.get("created_at") else None
        })

    # 3. Get q-ai-drug status
    q_ai_drug_online = await q_ai_drug_execution_service.http_executor.check_availability()

    return {
        "success": True,
        "data": {
            "latest_pipeline_run": latest_run,
            "project_metadata": {
                "last_pipeline_run_at": project.get("last_pipeline_run_at").isoformat() if project.get("last_pipeline_run_at") else None,
                "last_results_import_at": project.get("last_results_import_at").isoformat() if project.get("last_results_import_at") else None,
            },
            "imported_counts": {
                "molecules": molecules_count,
                "docking_results": docking_count,
                "gnina_results": gnina_count,
                "quantum_results": quantum_count,
                "simulation_results": simulation_count,
                "admet_results": admet_count,
                "reports": len(serialized_reports)
            },
            "generated_reports": serialized_reports,
            "q_ai_drug_status": {
                "online": q_ai_drug_online,
                "mode": settings.Q_AI_DRUG_EXECUTION_MODE
            }
        },
        "message": "Project pipeline execution and import summary fetched successfully."
    }

@router.get("/runs/{pipeline_run_id}", response_model=None)
async def get_pipeline_run(
    project_id: str = Path(...),
    pipeline_run_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    await check_project_and_authorize(project_id, user_id)

    pipeline_run = await pipeline_repository.get_pipeline_run_by_id_and_project(
        pipeline_run_id=pipeline_run_id,
        project_id=project_id
    )
    
    if not pipeline_run:
        raise AppException(
            status_code=404,
            code="PIPELINE_RUN_NOT_FOUND",
            message=f"Pipeline run '{pipeline_run_id}' not found in this project."
        )

    return {
        "success": True,
        "data": PipelineRunResponse.from_mongo(pipeline_run).model_dump(),
        "message": "Orchestration pipeline run details fetched successfully."
    }
