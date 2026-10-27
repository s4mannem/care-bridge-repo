"""Application configuration loaded from environment variables or `.env`."""

from __future__ import annotations

from functools import lru_cache
from carebridge._compat import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    google_cloud_project: str = "a4i-fulton-2026"
    google_cloud_location: str = "us-central1"
    bigquery_location: str = "US"
    bigquery_dataset: str = "a4i_health"
    bigquery_marta_dataset: str = "marta_gtfs"
    bigquery_audit_dataset: str = "external_demographic_audit"

    default_county_fips: str = "13121"
    default_county_name: str = "Fulton"
    default_state_abbr: str = "GA"

    gemini_model_fast: str = "gemini-2.5-flash"
    gemini_model_reasoning: str = "gemini-2.5-pro"

    mcp_bigquery_url: str = "http://127.0.0.1:5000/mcp"
    model_armor_enabled: bool = False
    model_armor_template_id: str = ""

    carebridge_api_key: str = "dev-carebridge-key"
    orchestration_timeout_seconds: float = 120.0
    max_audit_revisions: int = 1
    use_mock_data: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
