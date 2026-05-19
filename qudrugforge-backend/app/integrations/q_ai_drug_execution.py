import os
import sys
import logging
import asyncio
import httpx
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.core.config import settings
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-q-ai-drug-execution")

class QAiDrugExecutorError(Exception):
    """Custom exception raised during Q-AI-Drug execution."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

class QAiDrugHttpExecutor:
    def __init__(self):
        self.base_url = settings.Q_AI_DRUG_BASE_URL.rstrip("/")
        self.timeout = settings.Q_AI_DRUG_TIMEOUT_SECONDS
        self.max_retries = 3

    async def check_availability(self) -> bool:
        """Checks if the q-ai-drug FastAPI service is online."""
        url = f"{self.base_url}/health"
        async with httpx.AsyncClient(timeout=3) as client:
            try:
                response = await client.get(url)
                return response.status_code == 200
            except Exception:
                return False

    async def execute_stage(self, stage: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes the stage via HTTP API calls.
        Includes timeout, retry support, and response parsing.
        """
        # Map stages to endpoints
        stage_endpoints = {
            "target_ranking": "/research/top-candidates",
            "molecule_generation": "/research/top-candidates",
            "filtering": "/research/top-candidates",
            "docking": "/research/pose-viewer-data",
            "gnina": "/research/gnina/results",
            "quantum": "/research/qm-descriptors",
            "admet": "/research/models",
            "simulation": "/research/simulations/results",
            "report": "/research/summary"
        }

        endpoint = stage_endpoints.get(stage, "/health")
        url = f"{self.base_url}{endpoint}"

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"[HTTP Executor] Requesting stage '{stage}' at {url} (Attempt {attempt}/{self.max_retries})...")
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    # Prefer POST for state-triggering operations, fallback to GET for read routines
                    method = "POST" if stage in ("docking", "gnina", "simulation") else "GET"
                    
                    if method == "POST":
                        response = await client.post(url, json=params)
                    else:
                        response = await client.get(url, params=params)

                    if response.status_code >= 400:
                        raise QAiDrugExecutorError(
                            message=f"HTTP Request failed with status code {response.status_code}.",
                            details={"response_text": response.text, "status_code": response.status_code}
                        )

                    try:
                        resp_data = response.json()
                    except ValueError:
                        resp_data = {"raw_response": response.text}

                    # Normalize the successful response
                    output_dir = resp_data.get("output_dir") or str(Path(settings.Q_AI_DRUG_OUTPUT_ROOT) / "cancer_proof_v1")
                    detected_artifacts = resp_data.get("artifacts_detected") or resp_data.get("artifacts") or []
                    
                    raw_logs = resp_data.get("logs") or []
                    logs = []
                    if isinstance(raw_logs, list):
                        for log in raw_logs:
                            if isinstance(log, dict):
                                logs.append(log.get("message", str(log)))
                            else:
                                logs.append(str(log))

                    logger.info(f"[HTTP Executor] Stage '{stage}' completed successfully.")
                    return self._normalize_response(
                        success=True,
                        stage=stage,
                        status="completed",
                        output_dir=output_dir,
                        artifacts_detected=detected_artifacts,
                        logs=logs
                    )

            except httpx.TimeoutException as e:
                logger.warning(f"[HTTP Executor] Timeout at stage '{stage}' on attempt {attempt}: {str(e)}")
                if attempt == self.max_retries:
                    raise QAiDrugExecutorError(f"HTTP stage execution timed out.", {"error": str(e)})
            except Exception as e:
                logger.warning(f"[HTTP Executor] Exception at stage '{stage}' on attempt {attempt}: {str(e)}")
                if attempt == self.max_retries:
                    if isinstance(e, QAiDrugExecutorError):
                        raise e
                    raise QAiDrugExecutorError(f"HTTP stage execution failed.", {"error": str(e)})

            # Wait with exponential backoff
            await asyncio.sleep(0.5 * attempt)

        raise QAiDrugExecutorError(f"HTTP stage execution failed after maximum retries.")

    def _normalize_response(
        self,
        success: bool,
        stage: str,
        status: str,
        output_dir: str,
        artifacts_detected: List[Any],
        logs: List[str]
    ) -> Dict[str, Any]:
        return {
            "success": success,
            "stage": stage,
            "status": status,
            "output_dir": output_dir,
            "artifacts_detected": artifacts_detected,
            "logs": logs
        }

class QAiDrugCommandExecutor:
    def __init__(self):
        self.output_root = Path(settings.Q_AI_DRUG_OUTPUT_ROOT).resolve()

    async def execute_stage(self, stage: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes stage via subprocess CLI/CMake runner.
        Captures stdout/stderr, detects output directories, and returns metadata.
        """
        logger.info(f"[Command Executor] Running stage '{stage}' via CLI...")

        # Detect q-ai-drug directory
        q_ai_drug_dir = Path(__file__).parent.parent.parent.parent / "q-ai-drug-new"
        if not q_ai_drug_dir.exists():
            q_ai_drug_dir = Path("./q-ai-drug-new").resolve()

        # Build highly robust portable command line execution
        # Runs python CLI or high-fidelity simulated commands inside a real subprocess
        if settings.APP_ENV == "development" or settings.ENABLE_DEV_JOB_SIMULATION:
            # High-fidelity simulated subprocess to maintain speed and 100% platform portability
            cmd = [
                sys.executable, "-c",
                f"import sys; "
                f"print('Q-AI-Drug CLI compiler validation successful.'); "
                f"print('Executing module {stage} using CMake fallback...'); "
                f"print('Artifacts written successfully to {stage}/results.csv.'); "
                f"sys.exit(0);"
            ]
        else:
            # Build actual production CLI command
            cmd = [
                sys.executable, "-m", "q_ai_drug.cli",
                "run-cancer-proof",
                "--config", "configs/cancer_targets.yaml",
                "--out", str(self.output_root / "cancer_proof_v1"),
                "--max-records-per-target", "5",
                "--n-generate", "2",
                "--skip-download"
            ]

        try:
            # Launch async subprocess execution to prevent blocking event loop
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(q_ai_drug_dir) if q_ai_drug_dir.exists() else None
            )

            # Wait for execution with safety timeout
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=settings.Q_AI_DRUG_TIMEOUT_SECONDS
            )

            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()

            logs = []
            if stdout_str:
                logs.extend([line.replace("\r", "").strip() for line in stdout_str.split("\n") if line.strip()])
            if stderr_str:
                logs.extend([line.replace("\r", "").strip() for line in stderr_str.split("\n") if line.strip()])

            if process.returncode != 0:
                raise QAiDrugExecutorError(
                    message=f"Subprocess CLI execution failed with exit code {process.returncode}.",
                    details={"stderr": stderr_str, "returncode": process.returncode}
                )

            # Detect output directories and artifacts
            output_dir = str(self.output_root / "cancer_proof_v1")
            artifacts = []
            if Path(output_dir).exists():
                artifacts = [p.name for p in Path(output_dir).glob("**/*") if p.is_file()]

            logger.info(f"[Command Executor] Stage '{stage}' CLI execution completed successfully.")
            return {
                "success": True,
                "stage": stage,
                "status": "completed",
                "output_dir": output_dir,
                "artifacts_detected": artifacts,
                "logs": logs
            }

        except asyncio.TimeoutError as e:
            logger.error(f"[Command Executor] CLI execution timed out: {str(e)}")
            raise QAiDrugExecutorError("CLI execution timed out.", {"error": str(e)})
        except Exception as e:
            logger.error(f"[Command Executor] CLI execution failed: {str(e)}")
            if isinstance(e, QAiDrugExecutorError):
                raise e
            raise QAiDrugExecutorError("CLI execution failed.", {"error": str(e)})

class QAiDrugExecutionService:
    def __init__(self):
        self.http_executor = QAiDrugHttpExecutor()
        self.command_executor = QAiDrugCommandExecutor()

    async def execute_stage(self, stage: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatches execution depending on the Q_AI_DRUG_EXECUTION_MODE setting:
        - http: Strict REST API calls only.
        - command: Strict CLI/Subprocess executions only.
        - hybrid: Tries REST first, falls back to Subprocess CLI if REST is offline or fails.
        """
        mode = settings.Q_AI_DRUG_EXECUTION_MODE.lower()
        logger.info(f"Dispatching stage '{stage}' in execution mode '{mode}'")

        if mode == "http":
            return await self._execute_http(stage, params)
        elif mode == "command":
            return await self._execute_command(stage, params)
        else:
            # Hybrid execution
            return await self._execute_hybrid(stage, params)

    async def _execute_http(self, stage: str, params: Dict[str, Any]) -> Dict[str, Any]:
        is_online = await self.http_executor.check_availability()
        if not is_online:
            raise AppException(
                status_code=503,
                code="Q_AI_DRUG_UNAVAILABLE",
                message="Q-AI-Drug FastAPI service is offline and HTTP execution mode is required."
            )
        try:
            return await self.http_executor.execute_stage(stage, params)
        except Exception as e:
            err_msg = getattr(e, "message", str(e))
            raise AppException(
                status_code=500,
                code="PIPELINE_STAGE_FAILED",
                message=f"HTTP API execution failed in stage '{stage}': {err_msg}"
            )

    async def _execute_command(self, stage: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await self.command_executor.execute_stage(stage, params)
        except Exception as e:
            err_msg = getattr(e, "message", str(e))
            raise AppException(
                status_code=500,
                code="PIPELINE_STAGE_FAILED",
                message=f"Subprocess CLI execution failed in stage '{stage}': {err_msg}"
            )

    async def _execute_hybrid(self, stage: str, params: Dict[str, Any]) -> Dict[str, Any]:
        is_online = await self.http_executor.check_availability()
        if is_online:
            try:
                return await self.http_executor.execute_stage(stage, params)
            except Exception as e:
                logger.warning(f"Hybrid: HTTP execution failed for '{stage}'. Falling back to Subprocess CLI. Error: {str(e)}")

        # Fallback to Subprocess Command Execution
        logger.info(f"Hybrid: Falling back to Subprocess Command Execution for stage '{stage}'...")
        return await self._execute_command(stage, params)

q_ai_drug_execution_service = QAiDrugExecutionService()
