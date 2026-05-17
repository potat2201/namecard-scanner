from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = f"sqlite:///{DATA_DIR / 'namecards.db'}"
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    ollama_base_url: Optional[str] = None
    ollama_model: str = "gemma4:latest"
    ollama_timeout: float = 120.0
    lan_expose: bool = False
    cors_origins: str = "http://localhost:5173,http://localhost:3000"


settings = Settings()
