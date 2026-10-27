"""BigQuery access for the `a4i_health` dataset, configured from Settings.

Application Default Credentials, `query` returning dicts. The project comes
from config, and the client is created on first use so the app starts without
GCP. ui/scripts/build_mock.py reuses this class.
"""
from typing import Any

from ..config import Settings


class BigQueryRepo:
    def __init__(self, settings: Settings):
        self.project = settings.bq_project
        self.dataset = settings.bq_dataset
        self.views = settings.bq_use_sanitized_views
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.project and self.dataset)

    def client(self):
        if self._client is None:
            from google.cloud import bigquery  # import here: slow, and optional in tests

            self._client = bigquery.Client(project=self.project)
        return self._client

    def table(self, name: str) -> str:
        """Fully-qualified id, e.g. `proj.a4i_health.v_burden_tracts` (the sanitized view)."""
        if self.views and not name.startswith("v_"):
            name = f"v_{name}"
        return f"`{self.project}.{self.dataset}.{name}`"

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        from google.cloud import bigquery

        cfg = None
        if params:
            cfg = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter(k, _bq_type(v), v) for k, v in params.items()
            ])
        return [dict(r) for r in self.client().query(sql, job_config=cfg).result()]

    def ping(self) -> None:
        self.query("SELECT 1 AS ok")


def _bq_type(v: Any) -> str:
    if isinstance(v, bool):
        return "BOOL"
    if isinstance(v, int):
        return "INT64"
    if isinstance(v, float):
        return "FLOAT64"
    return "STRING"
