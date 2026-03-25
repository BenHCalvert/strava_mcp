#!/usr/bin/env python3
"""
One-time Strava OAuth authorization script.
Run this once to get your tokens, then the MCP server handles refresh automatically.

Usage:
    python auth.py
"""

import json
import os
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

TOKEN_FILE = Path(os.getenv("STRAVA_TOKEN_FILE", Path.home() / ".strava_token.json"))
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPES = "read,activity:read_all,profile:read_all"

# Shared state for the callback handler
auth_code = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family: sans-serif; padding: 40px;">
                <h2>&#x2705; Strava authorization successful!</h2>
                <p>You can close this tab and return to the terminal.</p>
                </body></html>
            """)
        else:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h2>Error: {error}</h2></body></html>".encode())

    def log_message(self, format, *args):
        pass  # Suppress request logs


def main():
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("\n❌  STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET are not set.")
        print("\nTo get these:")
        print("  1. Go to https://www.strava.com/settings/api")
        print("  2. Create an app (or use existing)")
        print("  3. Set 'Authorization Callback Domain' to: localhost")
        print("  4. Copy your Client ID and Client Secret")
        print("\nThen run:")
        print("  export STRAVA_CLIENT_ID=your_client_id")
        print("  export STRAVA_CLIENT_SECRET=your_client_secret")
        print("  python auth.py\n")
        return

    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&approval_prompt=force"
        f"&scope={SCOPES}"
    )

    print("\n🚴  Strava MCP Authorization")
    print("=" * 40)
    print(f"\nOpening browser for Strava login...")
    print(f"If it doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    # Start local server to catch the callback
    server = HTTPServer(("localhost", REDIRECT_PORT), CallbackHandler)
    server.timeout = 120
    print("Waiting for authorization (2 min timeout)...")
    server.handle_request()

    if not auth_code:
        print("❌  No authorization code received.")
        return

    # Exchange code for tokens
    print("Exchanging code for tokens...")
    resp = httpx.post("https://www.strava.com/oauth/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": auth_code,
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    tokens = resp.json()

    # Save tokens
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)

    athlete = tokens.get("athlete", {})
    name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
    print(f"\n✅  Authorized as: {name or 'Unknown athlete'}")
    print(f"   Tokens saved to: {TOKEN_FILE}")
    print(f"   Access token expires: {time.strftime('%Y-%m-%d %H:%M', time.localtime(tokens.get('expires_at', 0)))}")
    print("\nYou can now start the MCP server:\n  python server.py\n")


if __name__ == "__main__":
    main()
