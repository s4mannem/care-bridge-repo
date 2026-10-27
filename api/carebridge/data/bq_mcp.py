"""BigQuery over Google's managed (remote) MCP server, `https://bigquery.googleapis.com/mcp`.

ADK's `McpToolset` speaks Streamable HTTP to it with an OAuth bearer token from
Application Default Credentials (scope `bigquery`). Only `execute_sql_readonly`
is loaded, so the server itself refuses DML/DDL. Agents never see that tool:
they call named queries (`carebridge/tools/evidence.py`) that this client runs.
The server takes no query parameters, so `query` inlines them after checking
them against an allow-list pattern.

Needs, on the calling identity: roles/mcp.toolUser, roles/bigquery.jobUser,
roles/bigquery.dataViewer. Enabling bigquery.googleapis.com enables the server.
"""
import asyncio
import re
from types import SimpleNamespace
from typing import Any

from ..config import Settings
from ..security.owasp_guardrails import assert_readonly_sql

BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
MCP_SQL_TOOL = "execute_sql_readonly"
_PARAM_PATTERNS = {"fips": re.compile(r"^\d{5}$")}


class McpQueryError(RuntimeError):
    pass


class BigQueryMcp:
    def __init__(self, settings: Settings):
        self.project = settings.bq_project
        self.dataset = settings.bq_dataset
        self.url = settings.mcp_bigquery_url
        self._toolset = None
        self._creds = None

    def table(self, name: str) -> str:
        return f"`{self.project}.{self.dataset}.{name}`"

    async def _headers(self, _ctx: Any = None) -> dict[str, str]:
        import google.auth
        import google.auth.transport.requests

        if self._creds is None:
            self._creds, _ = google.auth.default(scopes=[BIGQUERY_SCOPE])
        if not self._creds.valid:
            await asyncio.to_thread(self._creds.refresh, google.auth.transport.requests.Request())
        return {"Authorization": f"Bearer {self._creds.token}", "x-goog-user-project": self.project}

    def toolset(self):
        if self._toolset is None:
            from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

            self._toolset = McpToolset(
                connection_params=StreamableHTTPConnectionParams(url=self.url, timeout=30.0),
                tool_filter=[MCP_SQL_TOOL], header_provider=self._headers)
        return self._toolset

    async def query(self, sql: str, params: dict[str, str] | None, context: Any = None) -> list[dict]:
        """Runs one read-only query through the MCP server.

        `context` is the calling ADK ToolContext or ReadonlyContext; outside an agent (scripts) leave it None.
        """
        # McpTool hands ReadonlyContext(context._invocation_context) to the header provider; ours ignores it.
        context = context or SimpleNamespace(_invocation_context=None)
        for k, v in (params or {}).items():
            if k not in _PARAM_PATTERNS or not _PARAM_PATTERNS[k].fullmatch(str(v)):
                raise ValueError(f"Query parameter {k}={v!r} is not allowed")
            sql = re.sub(rf"@{k}\b", f"'{v}'", sql)
        assert_readonly_sql(sql)
        tools = await self.toolset().get_tools(context)
        if not tools:
            raise McpQueryError(f"{self.url} offers no {MCP_SQL_TOOL} tool")
        result = await tools[0].run_async(args={"projectId": self.project, "query": sql}, tool_context=context)
        return decode_query_result(result)

    async def close(self) -> None:
        if self._toolset is not None:
            await self._toolset.close()


def decode_query_result(result: dict) -> list[dict]:
    """`execute_sql_readonly`'s jobs.query-shaped result (schema + f/v rows) -> list of dicts."""
    if result.get("isError") or "error" in result:
        text = " ".join(c.get("text", "") for c in result.get("content") or []) or str(result.get("error"))
        raise McpQueryError(f"BigQuery MCP query failed: {text[:500]}")
    body = result.get("structuredContent") or {}
    if not body.get("jobComplete", False):
        raise McpQueryError("BigQuery MCP query did not complete within its timeout")
    if body.get("pageToken"):
        raise McpQueryError("BigQuery MCP result is paged; the named queries must fit in one page")
    fields = body.get("schema", {}).get("fields", [])
    return [{f["name"]: _decode(c.get("v"), f) for f, c in zip(fields, row["f"])} for row in body.get("rows") or []]


def _decode(value: Any, field: dict) -> Any:
    if value is None:
        return None
    if field.get("mode") == "REPEATED":
        return [_decode(x.get("v"), {**field, "mode": "NULLABLE"}) for x in value]
    kind = field.get("type")
    if kind in ("RECORD", "STRUCT"):
        return {f["name"]: _decode(c.get("v"), f) for f, c in zip(field["fields"], value["f"])}
    if kind in ("INTEGER", "INT64"):
        return int(value)
    if kind in ("FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC"):
        return float(value)
    if kind in ("BOOLEAN", "BOOL"):
        return value == "true"
    return value
