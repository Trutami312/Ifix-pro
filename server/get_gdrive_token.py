#!/usr/bin/env python3
"""
Script mendapatkan Google Drive OAuth token via browser tablet.
Server berjalan di Codespace dan menangkap token callback.
"""
import http.server
import urllib.parse
import urllib.request
import json
import os
import sys
import threading
import configparser
import socket

# OAuth credentials dari Google Cloud Console project ifix-backup
# Set via environment variables or replace with your own credentials
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
SCOPE = "https://www.googleapis.com/auth/drive"

CODESPACE_NAME = os.environ.get("CODESPACE_NAME", "")
PORT = 53682

if CODESPACE_NAME:
    REDIRECT_URI = f"https://{CODESPACE_NAME}-{PORT}.app.github.dev/"
else:
    REDIRECT_URI = f"http://127.0.0.1:{PORT}/"

token_result = {}
server_instance = None

class OAuthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            code = params["code"][0]
            # Exchange code for token
            token_data = exchange_code(code)
            if token_data:
                token_result["token"] = token_data
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"""
                <html><body style='font-family:sans-serif;text-align:center;padding:50px'>
                <h1 style='color:green'>&#10003; Berhasil!</h1>
                <p>Google Drive berhasil disambungkan ke iFix Backup!</p>
                <p>Anda bisa menutup tab ini sekarang.</p>
                </body></html>
                """)
            else:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Error: gagal tukar token")
        elif "error" in params:
            error = params.get("error", ["unknown"])[0]
            token_result["error"] = error
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Error: {error}".encode())
        else:
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Menunggu callback...")

        # Stop server setelah menerima callback
        threading.Thread(target=server_instance.shutdown).start()

    def log_message(self, format, *args):
        pass  # Suppress log output

def exchange_code(code):
    """Tukar authorization code dengan access/refresh token."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"Error exchange token: {e}")
        return None

def save_rclone_config(token_data):
    """Simpan token ke rclone config."""
    config_path = os.path.expanduser("~/.config/rclone/rclone.conf")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)

    config = configparser.ConfigParser()
    config.read(config_path)

    # Token format yang dibutuhkan rclone
    token_json = json.dumps({
        "access_token": token_data.get("access_token"),
        "token_type": token_data.get("token_type", "Bearer"),
        "refresh_token": token_data.get("refresh_token"),
        "expiry": "0001-01-01T00:00:00Z"
    })

    if "gdrive" not in config:
        config["gdrive"] = {}

    config["gdrive"]["type"] = "drive"
    config["gdrive"]["scope"] = "drive"
    config["gdrive"]["token"] = token_json
    config["gdrive"]["root_folder_id"] = "1nz7aTpbtVc8Dave1ZJ2RaGkfm5s0ZXz8"

    # Hapus service_account_file jika ada
    config["gdrive"].pop("service_account_file", None)

    with open(config_path, "w") as f:
        config.write(f)

    print(f"\n✓ Token disimpan ke {config_path}")

def build_auth_url():
    """Buat URL untuk user buka di browser."""
    params = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
    })
    return f"https://accounts.google.com/o/oauth2/auth?{params}"

def main():
    global server_instance

    print("=" * 60)
    print("  iFix Pro - Google Drive OAuth Setup")
    print("=" * 60)

    if not CODESPACE_NAME:
        print("ERROR: Tidak berjalan di Codespace!")
        sys.exit(1)

    # Cek port tersedia
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.bind(("0.0.0.0", PORT))
        test_sock.close()
    except OSError:
        print(f"ERROR: Port {PORT} sudah dipakai. Jalankan: pkill -f rclone")
        sys.exit(1)

    auth_url = build_auth_url()

    print(f"\n📋 REDIRECT URI: {REDIRECT_URI}")
    print(f"\n🔗 BUKA URL INI DI BROWSER TABLET:")
    print(f"\n{auth_url}\n")
    print("=" * 60)
    print("Setelah login dan izinkan akses, server ini akan menangkap")
    print("token secara otomatis. Tunggu pesan 'Berhasil'.")
    print("=" * 60)
    print("\nMenunggu callback dari Google...")

    # Start server
    server_instance = http.server.HTTPServer(("0.0.0.0", PORT), OAuthHandler)
    server_instance.serve_forever()

    if "token" in token_result:
        save_rclone_config(token_result["token"])
        print("\n✓ Google Drive OAuth sukses!")
        print("Test koneksi...")
        result = os.system("rclone lsd gdrive: 2>&1")
        if result == 0:
            print("✓ Koneksi Google Drive berhasil!")
            os.system("rclone mkdir gdrive:test_oauth 2>/dev/null; rclone copy /tmp/test_gdrive.txt gdrive:test_oauth/ 2>&1 && echo '✓ Upload test OK!' || echo 'Upload masih gagal'")
        else:
            print("Ada masalah koneksi, cek rclone config")
    elif "error" in token_result:
        print(f"\n✗ Error: {token_result['error']}")

if __name__ == "__main__":
    main()
