from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field(default="local", alias="VIGNESH_ENV")
    host: str = Field(default="127.0.0.1", alias="VIGNESH_HOST")
    port: int = Field(default=8787, validation_alias=AliasChoices("VIGNESH_PORT", "PORT"))
    offline_mode: bool = Field(default=False, alias="VIGNESH_OFFLINE_MODE")

    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_model: str = Field(default="openai/gpt-5.2", alias="OPENROUTER_MODEL")
    openrouter_site_url: str = Field(
        default="https://github.com/TeddyJubu/vignesh", alias="OPENROUTER_SITE_URL"
    )
    openrouter_app_title: str = Field(
        default="Vignesh WhatsApp Agent", alias="OPENROUTER_APP_TITLE"
    )

    data_dir: Path = Field(default=Path("./data"), alias="VIGNESH_DATA_DIR")
    db_path: Path = Field(default=Path("./data/vignesh-agent.db"), alias="VIGNESH_DB_PATH")
    log_path: Path = Field(default=Path("./data/events.jsonl"), alias="VIGNESH_LOG_PATH")
    media_dir: Path = Field(default=Path("./data/media"), alias="VIGNESH_MEDIA_DIR")
    mcp_config: Path | None = Field(
        default=Path("./configs/mcp.example.json"),
        alias="VIGNESH_MCP_CONFIG",
    )
    skills_dir: Path = Field(default=Path("./skills"), alias="VIGNESH_SKILLS_DIR")

    wabot_endpoint: str = Field(default="http://127.0.0.1:7777", alias="WABOT_ENDPOINT")
    wabot_token: str | None = Field(default=None, alias="WABOT_TOKEN")
    wabot_inbound_token: str | None = Field(default=None, alias="WABOT_INBOUND_TOKEN")
    operator_token: str | None = Field(default=None, alias="VIGNESH_OPERATOR_TOKEN")

    send_policy: Literal["dry_run", "allowlist", "allow_all"] = Field(
        default="dry_run", alias="VIGNESH_SEND_POLICY"
    )
    allowed_recipients: set[str] = Field(default_factory=set, alias="VIGNESH_ALLOWED_RECIPIENTS")
    max_agent_turns: int = Field(default=8, alias="VIGNESH_MAX_AGENT_TURNS")

    @field_validator("allowed_recipients", mode="before")
    @classmethod
    def parse_allowed_recipients(cls, value: object) -> set[str]:
        if value is None or value == "":
            return set()
        if isinstance(value, str):
            return {part.strip() for part in value.split(",") if part.strip()}
        if isinstance(value, set):
            return value
        if isinstance(value, list | tuple):
            return {str(part).strip() for part in value if str(part).strip()}
        return set()

    @property
    def live_model_enabled(self) -> bool:
        return bool(self.openrouter_api_key and not self.offline_mode)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
