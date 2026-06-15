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
from app.schemas.orchestration import StageDispatchRequest, FailureType, FailureClassification

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
        self.output_root = Path(settings.Q_AI_DRUG_OUTPUT_ROOT).resolve()

    async def check_availability(self) -> bool:
        """Checks if the q-ai-drug FastAPI service is online."""
        url = f"{self.base_url}/health"
        async with httpx.AsyncClient(timeout=3) as client:
            try:
                response = await client.get(url)
                return response.status_code == 200
            except Exception:
                return False

    async def execute_stage(self, request: StageDispatchRequest, output_dir: str) -> Dict[str, Any]:
        """
        Executes the stage via HTTP API calls.
        Includes timeout, retry support, and response parsing.
        """
        stage = request.pipeline_stage
        params = request.parameters
        
        # Execution Capability Audit Enforcement
        # Fail loudly if stage does not support REST execution.
        valid_rest_triggers = {
            "gnina": "/research/gnina/start",
            "target_ranking": "/research/target-ranking/start",
            "quantum": "/research/quantum/start",
            "molecule_generation": "/research/molecule-generation/start",
            "filtering": "/research/filtering/start",
            "docking": "/research/docking/start",
            "admet": "/research/admet/start",
            "simulation": "/research/simulation/start",
            "report": "/research/report/start"
        }
        
        if stage not in valid_rest_triggers:
            # Throw explicitly instead of causing a 404 timeout
            raise QAiDrugExecutorError(
                f"Stage '{stage}' does not support REST execution. A true REST trigger route does not exist.", 
                {"failure_type": FailureType.execution_failure, "unsupported_rest": True}
            )

        endpoint = valid_rest_triggers[stage]
        url = f"{self.base_url}{endpoint}"
        
        # Inject isolated output directory into params if possible
        params["output_dir"] = output_dir

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"[HTTP Executor] Requesting stage '{stage}' (Job: {request.stage_job_id}) at {url} (Attempt {attempt}/{self.max_retries})...")
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=params)

                    if response.status_code >= 400:
                        raise QAiDrugExecutorError(
                            message=f"HTTP Request failed with status code {response.status_code}.",
                            details={"response_text": response.text, "status_code": response.status_code}
                        )

                    try:
                        resp_data = response.json()
                    except ValueError:
                        resp_data = {"raw_response": response.text}

                    # Poll for GNINA status if the stage is gnina
                    if stage == "gnina":
                        status_url = f"{self.base_url}/research/gnina/status"
                        poll_interval = 1.5
                        max_polls = 60  # 90 seconds
                        completed = False
                        
                        logger.info("[HTTP Executor] Starting GNINA status polling loop...")
                        for poll_attempt in range(max_polls):
                            await asyncio.sleep(poll_interval)
                            try:
                                async with httpx.AsyncClient(timeout=10) as poll_client:
                                    poll_resp = await poll_client.get(status_url)
                                    if poll_resp.status_code == 200:
                                        poll_data = poll_resp.json()
                                        status_val = poll_data.get("status")
                                        logger.info(f"[HTTP Executor] GNINA status poll: {status_val}")
                                        if status_val == "completed":
                                            completed = True
                                            break
                                        elif status_val in ("failed", "skipped"):
                                            raise QAiDrugExecutorError(
                                                message=f"GNINA run failed or skipped. Status: {status_val}",
                                                details=poll_data
                                            )
                                    else:
                                        logger.warning(f"[HTTP Executor] Failed to poll status. HTTP status: {poll_resp.status_code}")
                            except httpx.HTTPError as he:
                                logger.warning(f"[HTTP Executor] Connection error during poll: {str(he)}")
                        
                        if not completed:
                            raise QAiDrugExecutorError(
                                message="GNINA execution timed out during polling.",
                                details={"failure_type": FailureType.timeout}
                            )

                    # Normalize the successful response
                    # If GCS was used, output_dir should be the GCS URI
                    dyn_inputs = params.get("dynamic_inputs", {})
                    gcs_out_uri = dyn_inputs.get("gcs_output_uri")
                    if gcs_out_uri:
                        actual_output_dir = gcs_out_uri
                    else:
                        actual_output_dir = output_dir
                    
                    detected_artifacts = []
                    if Path(actual_output_dir).exists():
                        detected_artifacts = [p.name for p in Path(actual_output_dir).glob("**/*") if p.is_file()]

                    # Explicit Artifact Telemetry Requirement
                    logger.info(f"[ARTIFACT TELEMETRY] Stage: {stage}")
                    logger.info(f"[ARTIFACT TELEMETRY] Output Directory: {actual_output_dir}")
                    logger.info(f"[ARTIFACT TELEMETRY] Artifact Count: {len(detected_artifacts)}")
                    logger.info(f"[ARTIFACT TELEMETRY] Discovered Files: {detected_artifacts}")

                    raw_logs = resp_data.get("logs") or []
                    logs = []
                    if isinstance(raw_logs, list):
                        for log in raw_logs:
                            if isinstance(log, dict):
                                logs.append(log.get("message", str(log)))
                            else:
                                logs.append(str(log))
                    
                    logs.append(f"[ARTIFACT TELEMETRY] Stage: {stage}")
                    logs.append(f"[ARTIFACT TELEMETRY] Output Directory: {actual_output_dir}")
                    logs.append(f"[ARTIFACT TELEMETRY] Artifact Count: {len(detected_artifacts)}")
                    logs.append(f"[ARTIFACT TELEMETRY] Discovered Files: {detected_artifacts}")

                    logger.info(f"[HTTP Executor] Stage '{stage}' completed successfully.")
                    return self._normalize_response(
                        success=True,
                        stage=stage,
                        status="completed",
                        output_dir=actual_output_dir,
                        artifacts_detected=detected_artifacts,
                        logs=logs
                    )

            except httpx.TimeoutException as e:
                logger.warning(f"[HTTP Executor] Timeout at stage '{stage}' on attempt {attempt}: {str(e)}")
                if attempt == self.max_retries:
                    raise QAiDrugExecutorError(f"HTTP stage execution timed out.", {"error": str(e), "failure_type": FailureType.timeout})
            except Exception as e:
                logger.warning(f"[HTTP Executor] Exception at stage '{stage}' on attempt {attempt}: {str(e)}")
                if attempt == self.max_retries:
                    if isinstance(e, QAiDrugExecutorError):
                        raise e
                    raise QAiDrugExecutorError(f"HTTP stage execution failed.", {"error": str(e), "failure_type": FailureType.execution_failure})

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

    async def execute_stage(self, request: StageDispatchRequest, output_dir: str) -> Dict[str, Any]:
        """
        Executes stage via subprocess CLI/CMake runner.
        Captures stdout/stderr, detects output directories, and returns metadata.
        """
        stage = request.pipeline_stage
        logger.info(f"[Command Executor] Running stage '{stage}' (Job: {request.stage_job_id}) via CLI...")

        # Ensure isolated directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Detect q-ai-drug directory
        q_ai_drug_dir = Path(__file__).parent.parent.parent.parent.parent / "q-ai-drug-new"
        if not q_ai_drug_dir.exists():
            q_ai_drug_dir = Path("../../q-ai-drug-new").resolve()

        # Find Python executable that has q_ai_drug installed
        python_exe = os.environ.get("Q_AI_DRUG_PYTHON")
        if not python_exe:
            # Fallback path for Windows Conda environment 'qadn'
            conda_qadn_python = r"C:\Users\pc\anaconda3\envs\qadn\python.exe"
            if os.path.exists(conda_qadn_python):
                python_exe = conda_qadn_python
            else:
                python_exe = sys.executable

        # Build actual production CLI command to invoke the modular stage
        cmd = [
            python_exe, "-m", "q_ai_drug.cli",
            "run-stage",
            "--stage", stage,
            "--out", output_dir
        ]

        # Priority 1: Pass dynamic inputs to execution adapter
        import json
        dynamic_inputs = request.parameters.get("dynamic_inputs")
        if dynamic_inputs:
            inputs_json_path = Path(output_dir) / "dynamic_inputs.json"
            inputs_json_path.write_text(json.dumps(dynamic_inputs))
            cmd.extend(["--inputs-json", str(inputs_json_path)])
            logger.info(f"Injected dynamic inputs via {inputs_json_path}")

        import subprocess
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(q_ai_drug_dir / "src") + os.pathsep + env.get("PYTHONPATH", "")
            
            def run_sync():
                return subprocess.run(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(q_ai_drug_dir) if q_ai_drug_dir.exists() else None,
                    env=env,
                    text=True,
                    timeout=settings.Q_AI_DRUG_TIMEOUT_SECONDS
                )
            
            # Launch sync subprocess execution in thread to prevent blocking event loop
            try:
                process = await asyncio.to_thread(run_sync)
            except subprocess.TimeoutExpired as e:
                raise asyncio.TimeoutError(str(e))

            stdout_str = process.stdout.strip() if process.stdout else ""
            stderr_str = process.stderr.strip() if process.stderr else ""

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
            local_out = output_dir
            artifacts = []
            if Path(local_out).exists():
                artifacts = [p.name for p in Path(local_out).glob("**/*") if p.is_file()]

            logger.info(f"Subprocess wrapper output successfully parsed: {len(logs)} logs retrieved.")
            
            # Explicit Artifact Telemetry Requirement
            logger.info(f"[ARTIFACT TELEMETRY] Stage: {stage}")
            logger.info(f"[ARTIFACT TELEMETRY] Output Directory: {local_out}")
            logger.info(f"[ARTIFACT TELEMETRY] Artifact Count: {len(artifacts)}")
            logger.info(f"[ARTIFACT TELEMETRY] Discovered Files: {artifacts}")
            
            logs.append(f"[ARTIFACT TELEMETRY] Stage: {stage}")
            logs.append(f"[ARTIFACT TELEMETRY] Output Directory: {local_out}")
            logs.append(f"[ARTIFACT TELEMETRY] Artifact Count: {len(artifacts)}")
            logs.append(f"[ARTIFACT TELEMETRY] Discovered Files: {artifacts}")
            
            # If GCS was used, return GCS URI instead of local directory
            dyn_inputs = request.parameters.get("dynamic_inputs", {})
            gcs_out_uri = dyn_inputs.get("gcs_output_uri")
            final_output_dir = gcs_out_uri if gcs_out_uri else local_out
            
            return {
                "success": True,
                "stage": stage,
                "status": "completed",
                "output_dir": final_output_dir,
                "artifacts_detected": artifacts,
                "logs": logs
            }

        except asyncio.TimeoutError as e:
            logger.error(f"[Command Executor] CLI execution timed out: {str(e)}")
            raise QAiDrugExecutorError("CLI execution timed out.", {"error": str(e), "failure_type": FailureType.timeout})
        except Exception as e:
            logger.error(f"[Command Executor] CLI execution failed: {str(e)}")
            if isinstance(e, QAiDrugExecutorError):
                raise e
            raise QAiDrugExecutorError("CLI execution failed.", {"error": str(e), "failure_type": FailureType.execution_failure})

class QAiDrugExecutionService:
    def __init__(self):
        self.http_executor = QAiDrugHttpExecutor()
        self.command_executor = QAiDrugCommandExecutor()
        self.output_root = Path(settings.Q_AI_DRUG_OUTPUT_ROOT).resolve()

    async def execute_stage(self, request: StageDispatchRequest) -> Dict[str, Any]:
        """
        Dispatches execution depending on the Q_AI_DRUG_EXECUTION_MODE setting:
        - http: Strict REST API calls only.
        - command: Strict CLI/Subprocess executions only.
        - hybrid: Tries REST first, falls back to Subprocess CLI if REST is offline or fails.
        """
        mode = settings.Q_AI_DRUG_EXECUTION_MODE.lower()
        stage = request.pipeline_stage
        
        # Enforce isolated working directory for this Experiment
        isolated_output_dir = str(self.output_root / "runs" / request.experiment_id)
        
        logger.info(f"Dispatching stage '{stage}' in execution mode '{mode}' to '{isolated_output_dir}'")

        if mode == "http":
            return await self._execute_http(request, isolated_output_dir)
        elif mode == "command":
            return await self._execute_command(request, isolated_output_dir)
        else:
            # Hybrid execution
            return await self._execute_hybrid(request, isolated_output_dir)

    async def _execute_http(self, request: StageDispatchRequest, output_dir: str) -> Dict[str, Any]:
        is_online = await self.http_executor.check_availability()
        if not is_online:
            raise AppException(
                status_code=503,
                code="Q_AI_DRUG_UNAVAILABLE",
                message="Q-AI-Drug FastAPI service is offline and HTTP execution mode is required."
            )
        try:
            return await self.http_executor.execute_stage(request, output_dir)
        except QAiDrugExecutorError as e:
            raise AppException(
                status_code=500,
                code="PIPELINE_STAGE_FAILED",
                message=f"HTTP API execution failed in stage '{request.pipeline_stage}': {e.message}",
                details=e.details
            )
        except Exception as e:
            raise AppException(
                status_code=500,
                code="PIPELINE_STAGE_FAILED",
                message=f"HTTP API execution failed in stage '{request.pipeline_stage}': {str(e)}",
                details={"failure_type": FailureType.execution_failure}
            )

    async def _execute_command(self, request: StageDispatchRequest, output_dir: str) -> Dict[str, Any]:
        try:
            return await self.command_executor.execute_stage(request, output_dir)
        except QAiDrugExecutorError as e:
            raise AppException(
                status_code=500,
                code="PIPELINE_STAGE_FAILED",
                message=f"Subprocess CLI execution failed in stage '{request.pipeline_stage}': {e.message}",
                details=e.details
            )
        except Exception as e:
            raise AppException(
                status_code=500,
                code="PIPELINE_STAGE_FAILED",
                message=f"Subprocess CLI execution failed in stage '{request.pipeline_stage}': {str(e)}",
                details={"failure_type": FailureType.execution_failure}
            )

    async def _execute_hybrid(self, request: StageDispatchRequest, output_dir: str) -> Dict[str, Any]:
        is_online = await self.http_executor.check_availability()
        if is_online:
            try:
                return await self.http_executor.execute_stage(request, output_dir)
            except Exception as e:
                logger.warning(f"Hybrid: HTTP execution failed for '{request.pipeline_stage}'. Falling back to Subprocess CLI. Error: {str(e)}")

        # Fallback to Subprocess Command Execution
        logger.info(f"Hybrid: Falling back to Subprocess Command Execution for stage '{request.pipeline_stage}'...")
        return await self._execute_command(request, output_dir)

q_ai_drug_execution_service = QAiDrugExecutionService()
