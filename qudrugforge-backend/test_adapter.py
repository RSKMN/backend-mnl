import asyncio
import sys
import os

# Add backend to path so we can import internal services
sys.path.append("E:/rskmn/Npersonal/quinfosys/drug_discovery_research/work/mnl/backend-mnl/qudrugforge-backend")

from app.integrations.q_ai_drug_execution import q_ai_drug_execution_service
from app.schemas.orchestration import StageDispatchRequest

async def test():
    req = {
        "pipeline_run_id": "test_id",
        "experiment_id": "test_exp",
        "pipeline_stage": "target_ranking",
        "stage_job_id": "test_job",
        "engine": "default",
        "parameters": {}
    }
    req_obj = StageDispatchRequest(**req)
    try:
        res = await q_ai_drug_execution_service.execute_stage(req_obj)
        print("SUCCESS:", res)
    except Exception as e:
        import traceback
        traceback.print_exc()
        if hasattr(e, "details"):
            print("DETAILS:", e.details)

if __name__ == "__main__":
    asyncio.run(test())
