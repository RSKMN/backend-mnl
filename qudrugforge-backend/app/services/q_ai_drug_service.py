import logging
from typing import Any, Optional, Dict, List
from app.integrations.q_ai_drug_client import q_ai_drug_client, QAiDrugClientError
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.core.exceptions import AppException
from app.utils.datetime import utc_now
from app.core.config import settings

logger = logging.getLogger("q-ai-drug-service")

class QAiDrugService:
    async def check_workspace_access(self, workspace_id: str, user_id: str) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace"
            )
        return membership

    async def get_project_and_authorize(self, project_id: str, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        return project

    def _normalize(self, project_id: str, raw_response: Any) -> dict:
        now = utc_now().isoformat()
        
        items = []
        raw = {}
        
        if isinstance(raw_response, list):
            items = raw_response
        elif isinstance(raw_response, dict):
            raw = raw_response
            if "items" in raw_response and isinstance(raw_response["items"], list):
                items = raw_response["items"]
            elif "data" in raw_response and isinstance(raw_response["data"], list):
                items = raw_response["data"]
            else:
                items = []
        else:
            raw = {"value": raw_response}
            items = []
            
        return {
            "project_id": project_id,
            "source": "q-ai-drug",
            "items": items,
            "raw": raw,
            "last_synced_at": now
        }

    def _handle_client_error(self, e: QAiDrugClientError) -> AppException:
        if e.status_code == 503:
            return AppException(
                status_code=503,
                code="Q_AI_DRUG_UNAVAILABLE",
                message="The external q-ai-drug compute engine is currently offline or unreachable.",
                details={"base_url": settings.Q_AI_DRUG_BASE_URL, **e.details}
            )
        elif e.status_code == 408:
            return AppException(
                status_code=504,
                code="Q_AI_DRUG_TIMEOUT",
                message="Connection request to the q-ai-drug compute cluster timed out.",
                details={"base_url": settings.Q_AI_DRUG_BASE_URL, **e.details}
            )
        else:
            return AppException(
                status_code=502,
                code="Q_AI_DRUG_BAD_RESPONSE",
                message=f"Received bad or failing response from the q-ai-drug engine: {e.message}",
                details={"base_url": settings.Q_AI_DRUG_BASE_URL, **e.details}
            )

    async def health(self) -> dict:
        try:
            raw_res = await q_ai_drug_client.health()
            return {
                "available": True,
                "base_url": settings.Q_AI_DRUG_BASE_URL,
                "health": raw_res,
                "error": None
            }
        except QAiDrugClientError as e:
            return {
                "available": False,
                "base_url": settings.Q_AI_DRUG_BASE_URL,
                "health": None,
                "error": e.message
            }
        except Exception as e:
            return {
                "available": False,
                "base_url": settings.Q_AI_DRUG_BASE_URL,
                "health": None,
                "error": str(e)
            }

    async def get_top_candidates(self, project_id: str, user_id: str) -> dict:
        await self.get_project_and_authorize(project_id, user_id)
        try:
            raw_res = await q_ai_drug_client.get_top_candidates({"project_id": project_id})
            return self._normalize(project_id, raw_res)
        except QAiDrugClientError as e:
            raise self._handle_client_error(e)

    async def get_qm_descriptors(self, project_id: str, user_id: str) -> dict:
        await self.get_project_and_authorize(project_id, user_id)
        try:
            raw_res = await q_ai_drug_client.get_qm_descriptors({"project_id": project_id})
            return self._normalize(project_id, raw_res)
        except QAiDrugClientError as e:
            raise self._handle_client_error(e)

    async def get_qml_scores(self, project_id: str, user_id: str) -> dict:
        await self.get_project_and_authorize(project_id, user_id)
        try:
            raw_res = await q_ai_drug_client.get_qml_scores({"project_id": project_id})
            return self._normalize(project_id, raw_res)
        except QAiDrugClientError as e:
            raise self._handle_client_error(e)

    async def get_gnina_results(self, project_id: str, user_id: str) -> dict:
        await self.get_project_and_authorize(project_id, user_id)
        try:
            raw_res = await q_ai_drug_client.get_gnina_results({"project_id": project_id})
            return self._normalize(project_id, raw_res)
        except QAiDrugClientError as e:
            raise self._handle_client_error(e)

    async def get_models(self, project_id: str, user_id: str) -> dict:
        await self.get_project_and_authorize(project_id, user_id)
        try:
            raw_res = await q_ai_drug_client.get_models({"project_id": project_id})
            return self._normalize(project_id, raw_res)
        except QAiDrugClientError as e:
            raise self._handle_client_error(e)

    async def get_dashboard(self, project_id: str, user_id: str) -> dict:
        await self.get_project_and_authorize(project_id, user_id)
        try:
            raw_res = await q_ai_drug_client.get_dashboard({"project_id": project_id})
            return self._normalize(project_id, raw_res)
        except QAiDrugClientError as e:
            raise self._handle_client_error(e)

    async def get_research_summary(self, project_id: str, user_id: str) -> dict:
        await self.get_project_and_authorize(project_id, user_id)
        try:
            raw_res = await q_ai_drug_client.get_research_summary({"project_id": project_id})
            return self._normalize(project_id, raw_res)
        except QAiDrugClientError as e:
            raise self._handle_client_error(e)

    async def predict_with_model(self, project_id: str, payload: dict, user_id: str) -> dict:
        await self.get_project_and_authorize(project_id, user_id)
        try:
            # Inject project_id in predict payload if missing
            if "project_id" not in payload:
                payload["project_id"] = project_id
            raw_res = await q_ai_drug_client.predict_with_model(payload)
            return self._normalize(project_id, raw_res)
        except QAiDrugClientError as e:
            raise self._handle_client_error(e)

q_ai_drug_service = QAiDrugService()
