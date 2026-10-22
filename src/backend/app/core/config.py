from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    ENV: Literal["dev", "prod", "test"] = "dev"
    DATABASE_URL: str = "postgresql+psycopg://app:app@localhost:5432/orderagent"
    JWT_SECRET: str = "change-me"
    JWT_EXPIRE_MINUTES: int = 10080
    FRONTEND_URL: str = "http://localhost:3000"
    # how Meta and the dashboard reach this backend (ngrok URL in dev); used for /media links
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    MEDIA_DIR: Path = BACKEND_DIR / "media"

    LLM_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""

    WHATSAPP_VERIFY_TOKEN: str = ""
    WHATSAPP_APP_SECRET: str = ""
    WHATSAPP_GRAPH_VERSION: str = "v21.0"
    TOKEN_ENCRYPTION_KEY: str = ""


settings = Settings()
