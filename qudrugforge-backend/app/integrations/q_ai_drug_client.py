import httpx
import logging
from typing import Any, Optional, Dict

logger = logging.getLogger("q-ai-drug-client")

Q_AI_DRUG_ENDPOINTS = {
    "health": "/health",
    "dashboard": "/dashboard",
    "research_summary": "/research/summary",
    "top_candidates": "/research/top-candidates",
    "qm_descriptors": "/research/qm-descriptors",
    "qml_scores": "/research/qml-scores",
    "quantum_prefilter": "/research/quantum-prefilter",
    "quantum_kernel_scores": "/research/qml-scores",
    "pose_viewer_data": "/research/pose-viewer-data",
    "gnina_start": "/research/gnina/start",   # Phase 11 — may not exist yet in q-ai-drug
    "gnina_status": "/research/gnina/status",
    "gnina_log": "/research/gnina/log",
    "gnina_results": "/research/gnina/results",
    "models": "/research/models",
    "predict_with_model": "/research/models/predict",
    "simulation_start": "/research/simulations/start",
    "simulation_status": "/research/simulations/status",
    "simulation_log": "/research/simulations/log",
    "simulation_results": "/research/simulations/results",
    "md_stability": "/research/simulations/stability"
}

class QAiDrugClientError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}

class QAiDrugClient:
    def __init__(self):
        from app.core.config import settings
        self.base_url = settings.Q_AI_DRUG_BASE_URL.rstrip("/")
        self.timeout = settings.Q_AI_DRUG_TIMEOUT_SECONDS

    async def _request(
        self,
        method: str,
        endpoint_key: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Any:
        path = Q_AI_DRUG_ENDPOINTS.get(endpoint_key)
        if not path:
            raise QAiDrugClientError(f"Endpoint key '{endpoint_key}' not mapped.")
            
        url = f"{self.base_url}{path}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(method, url, params=params, json=json_data)
                
                if response.status_code >= 400:
                    logger.error(f"q-ai-drug request failed: {response.status_code} - {response.text}")
                    raise QAiDrugClientError(
                        message=f"Request to q-ai-drug failed with status code {response.status_code}.",
                        status_code=response.status_code,
                        details={"response_text": response.text, "url": url}
                    )
                
                try:
                    return response.json()
                except ValueError:
                    return {"raw": response.text}
                    
            except httpx.TimeoutException as e:
                logger.error(f"q-ai-drug timeout connecting to {url}: {str(e)}")
                raise QAiDrugClientError(
                    message="Request to q-ai-drug timed out.",
                    status_code=408,
                    details={"error": str(e), "url": url}
                )
            except httpx.RequestError as e:
                logger.error(f"q-ai-drug connection error connecting to {url}: {str(e)}")
                raise QAiDrugClientError(
                    message="Failed to connect to q-ai-drug service.",
                    status_code=503,
                    details={"error": str(e), "url": url}
                )

    async def health(self) -> Any:
        return await self._request("GET", "health")

    async def get_dashboard(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "dashboard", params=params)

    async def get_research_summary(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "research_summary", params=params)

    async def get_top_candidates(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "top_candidates", params=params)

    async def get_qm_descriptors(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "qm_descriptors", params=params)

    async def get_qml_scores(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "qml_scores", params=params)

    async def get_quantum_prefilter(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "quantum_prefilter", params=params)

    async def get_quantum_kernel_scores(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "quantum_kernel_scores", params=params)

    async def get_pose_viewer_data(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "pose_viewer_data", params=params)

    async def start_gnina(self, payload: Dict[str, Any]) -> Any:
        """
        POST /research/gnina/start

        Attempt to start a GNINA run via q-ai-drug. Returns the raw response
        if the endpoint exists. If q-ai-drug does not expose this route (current
        status as of Phase 11), raises QAiDrugClientError with status_code=404
        so the caller can log and fall back to artifact-import mode gracefully.
        """
        return await self._request("POST", "gnina_start", json_data=payload)

    async def get_gnina_status(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "gnina_status", params=params)

    async def get_gnina_log(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "gnina_log", params=params)

    async def get_gnina_results(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "gnina_results", params=params)

    async def get_models(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "models", params=params)

    async def predict_with_model(self, payload: Dict[str, Any]) -> Any:
        return await self._request("POST", "predict_with_model", json_data=payload)

    async def start_simulation(self, payload: Dict[str, Any]) -> Any:
        return await self._request("POST", "simulation_start", json_data=payload)

    async def get_simulation_status(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "simulation_status", params=params)

    async def get_simulation_log(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "simulation_log", params=params)

    async def get_simulation_results(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "simulation_results", params=params)

    async def get_md_stability(self, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self._request("GET", "md_stability", params=params)

q_ai_drug_client = QAiDrugClient()
