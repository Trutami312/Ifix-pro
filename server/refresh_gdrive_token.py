#!/usr/bin/env python3
"""
Script untuk refresh Google Drive OAuth token secara proaktif.
Jalankan via cron setiap 6 jam agar token selalu fresh.
Ini mengatasi masalah Google Cloud "Testing" mode dimana
refresh token expire setelah 7 hari jika tidak digunakan.

Usage:
    python3 refresh_gdrive_token.py

Cron (setiap 6 jam):
    0 */6 * * * /usr/bin/python3 /root/refresh_gdrive_token.py >> /var/log/gdrive_token_refresh.log 2>&1
"""
import json
import os
import urllib.request
import urllib.parse
import configparser
import datetime
import sys

RCLONE_CONF = os.path.expanduser("~/.config/rclone/rclone.conf")
REMOTE_NAME = "gdrive"

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def main():
    if not os.path.exists(RCLONE_CONF):
        log(f"ERROR: rclone config tidak ditemukan: {RCLONE_CONF}")
        sys.exit(1)

    # Parse rclone config
    config = configparser.ConfigParser()
    config.read(RCLONE_CONF)

    if REMOTE_NAME not in config:
        log(f"ERROR: remote '{REMOTE_NAME}' tidak ditemukan di rclone config")
        sys.exit(1)

    section = config[REMOTE_NAME]
    client_id = section.get("client_id", "")
    client_secret = section.get("client_secret", "")
    token_str = section.get("token", "")

    if not client_id or not client_secret:
        log("ERROR: client_id atau client_secret tidak ada di rclone config")
        sys.exit(1)

    if not token_str:
        log("ERROR: token tidak ada di rclone config")
        sys.exit(1)

    token_data = json.loads(token_str)
    refresh_token = token_data.get("refresh_token", "")

    if not refresh_token:
        log("ERROR: refresh_token tidak ada")
        sys.exit(1)

    # Refresh the token
    log("Refreshing Google Drive OAuth token...")
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
    except Exception as e:
        log(f"ERROR: Gagal refresh token: {e}")
        sys.exit(1)

    new_access_token = result.get("access_token")
    expires_in = result.get("expires_in", 3600)
    refresh_token_expires_in = result.get("refresh_token_expires_in")

    if not new_access_token:
        log(f"ERROR: Tidak dapat access token baru: {result}")
        sys.exit(1)

    # Calculate expiry
    expiry = (datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Update token in rclone config
    new_token = {
        "access_token": new_access_token,
        "token_type": "Bearer",
        "refresh_token": refresh_token,
        "expiry": expiry
    }

    # If Google returned a new refresh token, use it
    if "refresh_token" in result:
        new_token["refresh_token"] = result["refresh_token"]
        log("Got new refresh token from Google")

    config[REMOTE_NAME]["token"] = json.dumps(new_token)

    # Write back
    with open(RCLONE_CONF, "w") as f:
        config.write(f)

    os.chmod(RCLONE_CONF, 0o600)

    log(f"Token refreshed OK. Access token expires in {expires_in}s")
    if refresh_token_expires_in:
        days_left = refresh_token_expires_in / 86400
        log(f"Refresh token expires in {days_left:.1f} days")
        if days_left < 2:
            log("WARNING: Refresh token hampir expire! Perlu re-authorize.")

    # Quick test
    ret = os.system("rclone lsd gdrive: > /dev/null 2>&1")
    if ret == 0:
        log("Verification OK - rclone can access Google Drive")
    else:
        log("WARNING: rclone test failed after token refresh")

if __name__ == "__main__":
    main()
