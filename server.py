#!/usr/bin/env python3
"""Strava MCP Server — exposes Strava athlete activities, segments, stats, and gear via MCP."""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_URL = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/oauth/token"
TOKEN_FILE = Path(os.getenv("STRAVA_TOKEN_FILE", Path.home() / ".strava_token.json"))

# ── MCP Server ────────────────────────────────────────────────────────────────
mcp = FastMCP("strava_mcp")


# ── Token management ──────────────────────────────────────────────────────────

def _load_tokens() -> dict:
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return {}


def _save_tokens(tokens: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    """Exchange refresh token for a new access token."""
    resp = httpx.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    })
    resp.raise_for_status()
    return resp.json()


def _get_access_token() -> str:
    """Return a valid access token, refreshing if expired."""
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError(
            "STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET must be set. "
            "Create an app at https://www.strava.com/settings/api then run: "
            "python auth.py"
        )

    tokens = _load_tokens()
    if not tokens.get("refresh_token"):
        raise ValueError(
            "No Strava tokens found. Run 'python auth.py' first to authorize."
        )

    # Refresh if expired (with 5-min buffer)
    if tokens.get("expires_at", 0) < time.time() + 300:
        new_tokens = _refresh_access_token(client_id, client_secret, tokens["refresh_token"])
        tokens.update(new_tokens)
        _save_tokens(tokens)

    return tokens["access_token"]


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(path: str, params: dict = None) -> Any:
    """Make an authenticated GET request to the Strava API."""
    token = _get_access_token()
    # httpx serializes None as empty-string params (e.g. `before=`), which Strava
    # interprets as a real filter and returns zero results. Drop None values.
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    resp = httpx.get(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=clean_params,
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError("Strava rate limit hit (200 req/15min or 2000/day). Wait and retry.")
    if resp.status_code == 401:
        raise RuntimeError("Strava auth error — token may be invalid. Run 'python auth.py' again.")
    resp.raise_for_status()
    return resp.json()


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _handle_error(e: Exception) -> str:
    return f"Error: {type(e).__name__}: {e}"


def _ts(dt_str: Optional[str]) -> Optional[int]:
    """Convert YYYY-MM-DD string to Unix timestamp."""
    if not dt_str:
        return None
    return int(datetime.strptime(dt_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


# ── Input models ──────────────────────────────────────────────────────────────

class ActivitiesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    limit: int = Field(default=30, ge=1, le=200, description="Number of activities to return (1–200).")
    before: Optional[str] = Field(default=None, description="Filter activities before this date (YYYY-MM-DD).")
    after: Optional[str] = Field(default=None, description="Filter activities after this date (YYYY-MM-DD).")
    sport_type: Optional[str] = Field(
        default=None,
        description="Optional filter by sport type, e.g. 'Run', 'Ride', 'BackcountrySkiing', 'NordicSki', 'AlpineSki', 'Hike', 'MountainBikeRide'."
    )


class ActivityIdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    activity_id: int = Field(description="Strava activity ID (integer).")
    include_all_efforts: bool = Field(default=False, description="Include all segment efforts.")


class SegmentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    segment_id: int = Field(description="Strava segment ID.")


class AthleteStatsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    athlete_id: Optional[int] = Field(default=None, description="Athlete ID. Defaults to authenticated athlete.")


class StarredSegmentsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    page: int = Field(default=1, ge=1, description="Page number.")
    per_page: int = Field(default=30, ge=1, le=200, description="Results per page.")


# ── Tools: Athlete ────────────────────────────────────────────────────────────

@mcp.tool(
    name="strava_get_athlete",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_athlete() -> str:
    """Get the authenticated athlete's profile including name, location, weight, FTP, and follower counts.

    Returns:
        JSON object with full athlete profile.
    """
    try:
        return _json(_get("/athlete"))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="strava_get_athlete_stats",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_athlete_stats() -> str:
    """Get all-time and recent stats for the authenticated athlete: totals for rides, runs, swims, elevation, and more.

    Returns:
        JSON object with recent_ride_totals, recent_run_totals, all_time totals, ytd totals.
    """
    try:
        athlete = _get("/athlete")
        athlete_id = athlete["id"]
        return _json(_get(f"/athletes/{athlete_id}/stats"))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="strava_get_athlete_zones",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_athlete_zones() -> str:
    """Get heart rate and power zones for the authenticated athlete.

    Returns:
        JSON object with heart_rate and power zone distributions.
    """
    try:
        return _json(_get("/athlete/zones"))
    except Exception as e:
        return _handle_error(e)


# ── Tools: Activities ─────────────────────────────────────────────────────────

@mcp.tool(
    name="strava_list_activities",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_list_activities(params: ActivitiesInput) -> str:
    """List activities for the authenticated athlete, with optional date range and sport type filtering.

    Args:
        params.limit: Max activities to return (default 30, max 200).
        params.before: Only return activities before this date (YYYY-MM-DD).
        params.after: Only return activities after this date (YYYY-MM-DD).
        params.sport_type: Filter by sport, e.g. 'Run', 'BackcountrySkiing', 'MountainBikeRide'.

    Returns:
        JSON list of activity summaries with distance, duration, elevation, HR, and more.
    """
    try:
        # Strava paginates at 200/page max; fetch in pages if needed
        per_page = min(params.limit, 200)
        page = 1
        all_activities = []

        while len(all_activities) < params.limit:
            batch = _get("/athlete/activities", {
                "per_page": per_page,
                "page": page,
                "before": _ts(params.before),
                "after": _ts(params.after),
            })
            if not batch:
                break
            all_activities.extend(batch)
            if len(batch) < per_page:
                break
            page += 1

        all_activities = all_activities[:params.limit]

        if params.sport_type:
            all_activities = [
                a for a in all_activities
                if a.get("sport_type", "").lower() == params.sport_type.lower()
                or a.get("type", "").lower() == params.sport_type.lower()
            ]

        # Return a trimmed, useful summary
        summarized = []
        for a in all_activities:
            summarized.append({
                "id": a.get("id"),
                "name": a.get("name"),
                "sport_type": a.get("sport_type") or a.get("type"),
                "start_date_local": a.get("start_date_local"),
                "duration_min": round(a.get("moving_time", 0) / 60, 1),
                "elapsed_min": round(a.get("elapsed_time", 0) / 60, 1),
                "distance_km": round((a.get("distance") or 0) / 1000, 2),
                "elevation_gain_m": a.get("total_elevation_gain"),
                "avg_hr": a.get("average_heartrate"),
                "max_hr": a.get("max_heartrate"),
                "avg_watts": a.get("average_watts"),
                "calories": a.get("calories"),
                "kudos": a.get("kudos_count"),
                "achievement_count": a.get("achievement_count"),
                "description": a.get("description"),
                "gear_id": a.get("gear_id"),
            })
        return _json(summarized)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="strava_get_activity",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_activity(params: ActivityIdInput) -> str:
    """Get full details for a specific Strava activity including splits, segment efforts, and gear.

    Args:
        params.activity_id: Strava activity ID (from strava_list_activities).
        params.include_all_efforts: Include all segment efforts (default False).

    Returns:
        JSON object with complete activity detail.
    """
    try:
        return _json(_get(f"/activities/{params.activity_id}", {
            "include_all_efforts": params.include_all_efforts
        }))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="strava_get_activity_laps",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_activity_laps(params: ActivityIdInput) -> str:
    """Get lap data for a specific activity.

    Args:
        params.activity_id: Strava activity ID.

    Returns:
        JSON list of laps with pace, HR, distance, and elapsed time.
    """
    try:
        return _json(_get(f"/activities/{params.activity_id}/laps"))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="strava_get_activity_zones",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_activity_zones(params: ActivityIdInput) -> str:
    """Get heart rate and power zone distribution for a specific activity.

    Args:
        params.activity_id: Strava activity ID.

    Returns:
        JSON object with HR/power zone breakdowns for the activity.
    """
    try:
        return _json(_get(f"/activities/{params.activity_id}/zones"))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="strava_get_activity_kudoers",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_activity_kudoers(params: ActivityIdInput) -> str:
    """Get the list of athletes who gave kudos on a specific activity.

    Args:
        params.activity_id: Strava activity ID.

    Returns:
        JSON list of athletes who kudoed the activity.
    """
    try:
        return _json(_get(f"/activities/{params.activity_id}/kudos"))
    except Exception as e:
        return _handle_error(e)


# ── Tools: Segments ───────────────────────────────────────────────────────────

@mcp.tool(
    name="strava_get_segment",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_segment(params: SegmentInput) -> str:
    """Get details for a specific Strava segment including distance, grade, and hazard status.

    Args:
        params.segment_id: Strava segment ID.

    Returns:
        JSON object with segment details and athlete's PR.
    """
    try:
        return _json(_get(f"/segments/{params.segment_id}"))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="strava_get_segment_leaderboard",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_segment_leaderboard(params: SegmentInput) -> str:
    """Get the leaderboard for a segment (top 10 efforts).

    Args:
        params.segment_id: Strava segment ID.

    Returns:
        JSON object with top efforts and athlete rankings.
    """
    try:
        return _json(_get(f"/segments/{params.segment_id}/leaderboard"))
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="strava_get_starred_segments",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_starred_segments(params: StarredSegmentsInput) -> str:
    """List segments starred by the authenticated athlete.

    Args:
        params.page: Page number (default 1).
        params.per_page: Results per page (default 30, max 200).

    Returns:
        JSON list of starred segments with distance, grade, and PR info.
    """
    try:
        return _json(_get("/segments/starred", {
            "page": params.page,
            "per_page": params.per_page,
        }))
    except Exception as e:
        return _handle_error(e)


# ── Tools: Gear ───────────────────────────────────────────────────────────────

@mcp.tool(
    name="strava_get_gear",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_gear(gear_id: str) -> str:
    """Get details for a specific piece of gear (bike, shoes) including total distance logged.

    Args:
        gear_id: Gear ID string (e.g. 'b12345' for bikes, 'g12345' for shoes). Found in activity data.

    Returns:
        JSON object with gear name, brand, model, and total distance.
    """
    try:
        return _json(_get(f"/gear/{gear_id}"))
    except Exception as e:
        return _handle_error(e)


# ── Tools: Routes ─────────────────────────────────────────────────────────────

@mcp.tool(
    name="strava_get_athlete_routes",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def strava_get_athlete_routes() -> str:
    """List routes created by the authenticated athlete.

    Returns:
        JSON list of routes with distance, elevation, and estimated time.
    """
    try:
        athlete = _get("/athlete")
        athlete_id = athlete["id"]
        return _json(_get(f"/athletes/{athlete_id}/routes"))
    except Exception as e:
        return _handle_error(e)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
