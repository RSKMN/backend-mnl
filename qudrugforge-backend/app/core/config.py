from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    QuDrugForge application configuration settings loader.
    Leverages pydantic-settings to automatically pull parameters from environment variables
    or a local .env configuration file.
    """
    APP_NAME: str = Field(default="QuDrugForge Backend")
    APP_ENV: str = Field(default="development")
    APP_DEBUG: bool = Field(default=True)

    API_V1_PREFIX: str = Field(default="/api/v1")

    # Database Configuration (MongoDB)
    MONGODB_URI: str = Field(default="mongodb://127.0.0.1:27017")
    MONGODB_DATABASE: str = Field(default="qudrugforge_dev")

    # Storage Configuration
    LOCAL_STORAGE_ROOT: str = Field(default="./storage")
    STORAGE_PROVIDER: str = Field(default="local")
    MAX_UPLOAD_SIZE_MB: int = Field(default=200)


    # Authentication Options
    JWT_SECRET_KEY: str = Field(default="change-this-in-development")
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)

    # Compute Cluster Coordinates
    Q_AI_DRUG_BASE_URL: str = Field(default="http://127.0.0.1:8000")
    Q_AI_DRUG_TIMEOUT_SECONDS: int = Field(default=30)
    Q_AI_DRUG_ENABLED: bool = Field(default=True)

    # Network / CORS Coordinates
    FRONTEND_URL: str = Field(default="http://localhost:3000")
    CORS_ORIGINS: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")

    # Q-AI-Drug Importer Settings
    Q_AI_DRUG_OUTPUT_ROOT: str = Field(default="../q-ai-drug/outputs")
    Q_AI_DRUG_IMPORT_ALLOW_ABSOLUTE_PATHS: bool = Field(default=False)

    # Phase 9: Experiment Dev Job Simulation Settings
    ENABLE_DEV_JOB_SIMULATION: bool = Field(default=True)
    JOB_SIMULATION_STEP_SECONDS: int = Field(default=1)

    # Phase 20.2: Q-AI-Drug Execution Mode (http, command, hybrid)
    Q_AI_DRUG_EXECUTION_MODE: str = Field(default="hybrid")


    @property
    def cors_origins_list(self) -> List[str]:
        """Parse comma-separated CORS origin strings into standard list coordinates."""
        if not self.CORS_ORIGINS:
            return []
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    # Pydantic v2 modern model configuration block
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

# Instantiate the singular global settings container
settings = Settings()
