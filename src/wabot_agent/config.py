from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
    )

    env: str = Field(
        default="local", validation_alias=AliasChoices("WABOT_AGENT_ENV", "VIGNESH_ENV")
    )
    host: str = Field(
        default="127.0.0.1", validation_alias=AliasChoices("WABOT_AGENT_HOST", "VIGNESH_HOST")
    )
    port: int = Field(
        default=8787, validation_alias=AliasChoices("WABOT_AGENT_PORT", "VIGNESH_PORT", "PORT")
    )
    offline_mode: bool = Field(
        default=False,
        validation_alias=AliasChoices("WABOT_AGENT_OFFLINE_MODE", "VIGNESH_OFFLINE_MODE"),
    )

    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_model: str = Field(default="openai/gpt-4.1-mini", alias="OPENROUTER_MODEL")
    openrouter_site_url: str = Field(
        default="https://github.com/TeddyJubu/wabot-agent", alias="OPENROUTER_SITE_URL"
    )
    openrouter_app_title: str = Field(default="wabot-agent", alias="OPENROUTER_APP_TITLE")

    model_provider: Literal["openrouter", "ollama", "ollama_cloud"] = Field(
        default="openrouter",
        validation_alias=AliasChoices(
            "WABOT_AGENT_MODEL_PROVIDER", "VIGNESH_MODEL_PROVIDER", "LLM_PROVIDER"
        ),
    )
    ollama_model: str = Field(
        default="gemma4:31b-cloud",
        validation_alias=AliasChoices("OLLAMA_MODEL", "WABOT_AGENT_OLLAMA_MODEL"),
    )
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434/v1",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "WABOT_AGENT_OLLAMA_BASE_URL"),
    )
    ollama_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OLLAMA_API_KEY", "WABOT_AGENT_OLLAMA_API_KEY"),
    )
    ollama_cloud_base_url: str = Field(
        default="https://ollama.com/v1",
        validation_alias=AliasChoices(
            "OLLAMA_CLOUD_BASE_URL", "WABOT_AGENT_OLLAMA_CLOUD_BASE_URL"
        ),
    )

    data_dir: Path = Field(
        default=Path("./data"),
        validation_alias=AliasChoices("WABOT_AGENT_DATA_DIR", "VIGNESH_DATA_DIR"),
    )
    db_path: Path = Field(
        default=Path("./data/wabot-agent.db"),
        validation_alias=AliasChoices("WABOT_AGENT_DB_PATH", "VIGNESH_DB_PATH"),
    )
    log_path: Path = Field(
        default=Path("./data/events.jsonl"),
        validation_alias=AliasChoices("WABOT_AGENT_LOG_PATH", "VIGNESH_LOG_PATH"),
    )
    media_dir: Path = Field(
        default=Path("./data/media"),
        validation_alias=AliasChoices("WABOT_AGENT_MEDIA_DIR", "VIGNESH_MEDIA_DIR"),
    )
    mcp_config: Path | None = Field(
        default=Path("./configs/mcp.example.json"),
        validation_alias=AliasChoices("WABOT_AGENT_MCP_CONFIG", "VIGNESH_MCP_CONFIG"),
    )
    skills_dir: Path = Field(
        default=Path("./skills"),
        validation_alias=AliasChoices("WABOT_AGENT_SKILLS_DIR", "VIGNESH_SKILLS_DIR"),
    )
    runtime_overrides_path: Path = Field(
        default=Path("./data/runtime_overrides.json"),
        validation_alias=AliasChoices(
            "WABOT_AGENT_RUNTIME_OVERRIDES_PATH", "VIGNESH_RUNTIME_OVERRIDES_PATH"
        ),
    )

    wabot_endpoint: str = Field(default="http://127.0.0.1:7777", alias="WABOT_ENDPOINT")
    wabot_token: str | None = Field(default=None, alias="WABOT_TOKEN")
    wabot_token_file: Path | None = Field(
        default=Path("~/.config/wabot/token"), alias="WABOT_TOKEN_FILE"
    )
    wabot_inbound_token: str | None = Field(default=None, alias="WABOT_INBOUND_TOKEN")
    wabot_home: Path | None = Field(default=None, alias="WABOT_AGENT_WABOT_HOME")
    wabot_restart_command: str | None = Field(
        default=None, alias="WABOT_AGENT_WABOT_RESTART_COMMAND"
    )
    operator_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WABOT_AGENT_OPERATOR_TOKEN", "VIGNESH_OPERATOR_TOKEN"),
    )
    dashboard_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "WABOT_AGENT_DASHBOARD_PASSWORD", "VIGNESH_DASHBOARD_PASSWORD"
        ),
    )

    send_policy: Literal["dry_run", "allowlist", "allow_all", "owner"] = Field(
        default="allow_all",
        validation_alias=AliasChoices("WABOT_AGENT_SEND_POLICY", "VIGNESH_SEND_POLICY"),
    )
    # NoDecode disables pydantic-settings' JSON pre-pass on env values so the
    # validator below can accept an empty string from `.env` without a JSON error.
    allowed_recipients: Annotated[set[str], NoDecode] = Field(
        default_factory=set,
        validation_alias=AliasChoices(
            "WABOT_AGENT_ALLOWED_RECIPIENTS", "VIGNESH_ALLOWED_RECIPIENTS"
        ),
    )
    owner_numbers: Annotated[set[str], NoDecode] = Field(
        default_factory=set,
        validation_alias=AliasChoices(
            "WABOT_AGENT_OWNER_NUMBERS", "VIGNESH_OWNER_NUMBERS"
        ),
    )
    max_agent_turns: int = Field(
        default=15,
        validation_alias=AliasChoices("WABOT_AGENT_MAX_AGENT_TURNS", "VIGNESH_MAX_AGENT_TURNS"),
    )
    agent_temperature: float = Field(
        default=0.35,
        validation_alias=AliasChoices(
            "WABOT_AGENT_TEMPERATURE", "VIGNESH_TEMPERATURE", "WABOT_AGENT_AGENT_TEMPERATURE"
        ),
    )
    auto_reply_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "WABOT_AGENT_AUTO_REPLY", "VIGNESH_AUTO_REPLY", "WABOT_AGENT_AUTO_REPLY_ENABLED"
        ),
    )
    vision_attach_images: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "WABOT_AGENT_VISION_ATTACH_IMAGES", "VIGNESH_VISION_ATTACH_IMAGES"
        ),
    )
    file_process_inbound: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "WABOT_AGENT_FILE_PROCESS_INBOUND", "VIGNESH_FILE_PROCESS_INBOUND"
        ),
    )
    file_excerpt_limit: int = Field(
        default=12_000,
        validation_alias=AliasChoices(
            "WABOT_AGENT_FILE_EXCERPT_LIMIT", "VIGNESH_FILE_EXCERPT_LIMIT"
        ),
    )
    file_max_process_bytes: int = Field(
        default=20 * 1024 * 1024,
        validation_alias=AliasChoices(
            "WABOT_AGENT_FILE_MAX_PROCESS_BYTES", "VIGNESH_FILE_MAX_PROCESS_BYTES"
        ),
    )
    file_use_system_tools: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "WABOT_AGENT_FILE_USE_SYSTEM_TOOLS", "VIGNESH_FILE_USE_SYSTEM_TOOLS"
        ),
    )
    file_ocr_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("WABOT_AGENT_FILE_OCR_ENABLED", "VIGNESH_FILE_OCR_ENABLED"),
    )
    whisper_model: str = Field(
        default="tiny",
        validation_alias=AliasChoices("WABOT_AGENT_WHISPER_MODEL", "VIGNESH_WHISPER_MODEL"),
    )
    whisper_model_owner: str = Field(
        default="base",
        validation_alias=AliasChoices(
            "WABOT_AGENT_WHISPER_MODEL_OWNER", "VIGNESH_WHISPER_MODEL_OWNER"
        ),
    )
    whisper_max_seconds: int = Field(
        default=90,
        validation_alias=AliasChoices(
            "WABOT_AGENT_WHISPER_MAX_SECONDS", "VIGNESH_WHISPER_MAX_SECONDS"
        ),
    )
    media_download_attempts: int = Field(
        default=5,
        validation_alias=AliasChoices(
            "WABOT_AGENT_MEDIA_DOWNLOAD_ATTEMPTS", "VIGNESH_MEDIA_DOWNLOAD_ATTEMPTS"
        ),
    )
    media_download_retry_seconds: float = Field(
        default=0.5,
        validation_alias=AliasChoices(
            "WABOT_AGENT_MEDIA_DOWNLOAD_RETRY_SECONDS",
            "VIGNESH_MEDIA_DOWNLOAD_RETRY_SECONDS",
        ),
    )

    cf_access_team_domain: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN", "VIGNESH_CF_ACCESS_TEAM_DOMAIN"
        ),
    )
    cf_access_aud: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "WABOT_AGENT_CF_ACCESS_AUD", "VIGNESH_CF_ACCESS_AUD"
        ),
    )
    cf_access_required: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "WABOT_AGENT_CF_ACCESS_REQUIRED", "VIGNESH_CF_ACCESS_REQUIRED"
        ),
    )

    @field_validator("cf_access_team_domain", "cf_access_aud", mode="before")
    @classmethod
    def empty_cf_access_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("allowed_recipients", "owner_numbers", mode="before")
    @classmethod
    def parse_recipient_set(cls, value: object) -> set[str]:
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
        if self.offline_mode:
            return False
        if self.model_provider == "openrouter":
            return bool(self.openrouter_api_key)
        if self.model_provider == "ollama_cloud":
            return bool(self.ollama_api_key)
        return True

    @property
    def resolved_wabot_token(self) -> str | None:
        if self.wabot_token:
            return self.wabot_token
        if not self.wabot_token_file:
            return None
        token_path = self.wabot_token_file.expanduser()
        try:
            token = token_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return token or None

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
