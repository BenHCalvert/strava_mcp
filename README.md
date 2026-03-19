# Strava MCP Server

Exposes your Strava data — activities, segments, stats, gear, and routes — as MCP tools for use with Claude Desktop.

Unlike Garmin, Strava uses **official OAuth2**, so you'll need to create a free Strava API app and do a one-time authorization. After that, tokens refresh automatically.

---

## Setup

### Step 1: Create a Strava API app

1. Go to [https://www.strava.com/settings/api](https://www.strava.com/settings/api)
2. Fill in the form:
   - **Application Name**: anything (e.g. "My MCP")
   - **Category**: Other
   - **Authorization Callback Domain**: `localhost`
3. Copy your **Client ID** and **Client Secret**

### Step 2: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Authorize (one-time)

```bash
export STRAVA_CLIENT_ID=your_client_id
export STRAVA_CLIENT_SECRET=your_client_secret

python auth.py
```

This opens your browser, you click "Authorize", and tokens are saved to `~/.strava_token.json`. You won't need to do this again — the server auto-refreshes tokens.

### Step 4: Add to Claude Desktop config

In `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "strava": {
      "command": "python3",
      "args": ["/path/to/strava_mcp/server.py"],
      "env": {
        "STRAVA_CLIENT_ID": "your_client_id",
        "STRAVA_CLIENT_SECRET": "your_client_secret"
      }
    }
  }
}
```

Quit and relaunch Claude Desktop.

---

## Available Tools

### Athlete
| Tool | Description |
|------|-------------|
| `strava_get_athlete` | Full profile: name, location, weight, FTP |
| `strava_get_athlete_stats` | All-time and YTD totals for rides, runs, swims |
| `strava_get_athlete_zones` | HR and power zones |

### Activities
| Tool | Description |
|------|-------------|
| `strava_list_activities` | List activities with date/type filters |
| `strava_get_activity` | Full activity detail with segment efforts |
| `strava_get_activity_laps` | Lap splits |
| `strava_get_activity_zones` | HR/power zone breakdown for an activity |
| `strava_get_activity_kudoers` | Who kudoed an activity |

### Segments
| Tool | Description |
|------|-------------|
| `strava_get_segment` | Segment details and your PR |
| `strava_get_segment_leaderboard` | Top 10 efforts on a segment |
| `strava_get_starred_segments` | Your starred segments |

### Gear & Routes
| Tool | Description |
|------|-------------|
| `strava_get_gear` | Bike/shoe details and total distance logged |
| `strava_get_athlete_routes` | Saved routes |

---

## Sport Type Filter Examples

Use `strava_list_activities` with `sport_type` set to:
- `BackcountrySkiing` — ski tours
- `AlpineSki` — resort days
- `NordicSki` — XC skiing
- `MountainBikeRide` — MTB
- `Run` / `TrailRun`
- `Ride` — road cycling
- `Hike`

## Notes

- Uses the official Strava API v3
- Rate limits: 200 requests per 15 minutes, 2000 per day
- Requires `activity:read_all` scope (requested automatically by `auth.py`)
- Token file stored at `~/.strava_token.json` — keep this private
