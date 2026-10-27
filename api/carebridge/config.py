"""Settings, read from the environment.

`CAREBRIDGE_*` variables configure the gateway. The BigQuery and Google Cloud
names (`BQ_PROJECT`, `GOOGLE_CLOUD_PROJECT`, ...) are the ones ADK and the
agents use, so one shared `.env` at the repo root serves every component.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAREBRIDGE_",
        # Later files win: api/.env overrides the shared repo-root .env.
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "api" / ".env"),
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Flutter web picks a random localhost port in dev, hence the regex.
    cors_origins: list[str] = []
    cors_origin_regex: str | None = r"http://(localhost|127\.0\.0\.1)(:\d+)?"

    bq_project: str | None = Field(None, validation_alias=AliasChoices("CAREBRIDGE_BQ_PROJECT", "BQ_PROJECT"))
    bq_dataset: str = Field("a4i_health", validation_alias=AliasChoices("CAREBRIDGE_BQ_DATASET", "BQ_DATASET"))
    gcp_project: str | None = Field(None, validation_alias=AliasChoices("CAREBRIDGE_GCP_PROJECT", "GOOGLE_CLOUD_PROJECT"))
    gcp_location: str | None = Field(None, validation_alias=AliasChoices("CAREBRIDGE_GCP_LOCATION", "GOOGLE_CLOUD_LOCATION"))

    # Which runner answers POST /v1/plan. "stub" returns the recorded plans in
    # carebridge/mocks/recorded/; "adk" needs the `agents` extra.
    agent_engine: Literal["stub", "adk"] = "stub"
    # The UI gives up at 130 s; finish (or fail) before it does.
    plan_timeout_s: float = 120.0
    # Pace of the stub runner's streamed events: 1.0 = recorded timing, 0 = instant.
    stub_stream_pace: float = 1.0

    # Where human review state lives: "memory" (tests, local) or "firestore" (Cloud Run).
    review_store: Literal["memory", "firestore"] = "memory"
    firestore_database: str = "(default)"

    # From the plan 00 foundation. Fulton is the county the demo is built on.
    default_county_fips: str = "13121"
    default_county_name: str = "Fulton"
    default_state_abbr: str = "GA"
    bq_marta_dataset: str = "marta_gtfs"
    # Auditor-only; the planner's service account must not be able to read it.
    bq_audit_dataset: str = "external_demographic_audit"

    # Gemini 3.x is required by the challenge (plan 00 had 2.5).
    gemini_model_fast: str = "gemini-3.6-flash"
    gemini_model_reasoning: str = "gemini-3.6-flash"
    # Google-managed BigQuery MCP server (Streamable HTTP); the Health & Access agent queries through it.
    mcp_bigquery_url: str = "https://bigquery.googleapis.com/mcp"
    model_armor_enabled: bool = False
    model_armor_template_id: str = ""
    max_audit_revisions: int = 1

    # Names the team's agents read (data_plane, mobility, auditor).
    bigquery_location: str = "US"
    use_mock_data: bool = False  # never on in a deployment: the data_plane would serve fixtures
    carebridge_api_key: str = ""

    @property
    def google_cloud_project(self) -> str | None:
        return self.gcp_project or self.bq_project

    @property
    def bigquery_dataset(self) -> str:
        return self.bq_dataset


@lru_cache
def get_settings() -> Settings:
    return Settings()
