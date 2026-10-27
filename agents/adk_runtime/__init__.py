"""Runs the team's agents (`carebridge/`, a copy of the repo's top-level package) on real ADK.

`graph.py` is the same adapter the API uses (`api/carebridge/agents/coordinator/adk_adapter.py`):
it builds the coordinator graph from the team's agent builders on ADK's own
classes. `pacing.py` spaces out Gemini calls to stay under the per-minute quota.
"""
