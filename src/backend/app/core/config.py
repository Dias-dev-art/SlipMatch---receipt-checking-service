from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    ENV: Literal["dev", "prod", "test"] = "dev"
    DATABASE_URL: str = "postgresql+psycopg://app:app@localhost:5432/orderagent"
    JWT_SECRET: str = "change-me"
    JWT_EXPIRE_MINUTES: int = 10080
    FRONTEND_URL: str = "http://localhost:3000"
    # how Telegram and the dashboard reach this backend (ngrok URL in dev); webhook + /media links
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    # the exported dashboard (`npm run build` in src/frontend); served at / when it exists
    FRONTEND_DIST: Path = REPO_ROOT / "src" / "frontend" / "out"

    LLM_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""

    # one Telegram bot (from @BotFather) that customers of every business order through
    TELEGRAM_BOT_TOKEN: str = ""
    # without @; shop links are t.me/<username>?start=<shop_code>
    TELEGRAM_BOT_USERNAME: str = ""
    # Telegram sends it back in X-Telegram-Bot-Api-Secret-Token on every webhook call
    TELEGRAM_WEBHOOK_SECRET: str = ""
    # shop_code for chats that opened the bot without a shop link (demo: one shop)
    TELEGRAM_DEFAULT_SHOP: str = ""

    @field_validator("DATABASE_URL")
    @classmethod
    def use_psycopg(cls, url: str) -> str:
        """Hosts (Replit, Supabase) give `postgresql://`; only the psycopg 3 driver is installed."""
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url


settings = Settings()
