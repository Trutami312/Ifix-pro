#!/usr/bin/env python3
"""
Helper: Setup rclone dengan Google Service Account
Jalankan: python3 /workspaces/Ifix-pro/server/setup_gdrive_sa.py
"""
import os, json, subprocess, sys

RCLONE_CONF = os.path.expanduser("~/.config/rclone/rclone.conf")
SA_FILE     = "/opt/gdrive_service_account.json"

def log(msg): print(f"  {msg}")

print()
print("=" * 55)
print("  Setup Google Drive via Service Account")
print("=" * 55)
print()
print("Paste isi JSON Service Account di bawah ini.")
print("(Buka file JSON yang didownload, select all, copy, paste)")
print("Setelah paste, tekan Enter lalu ketik: DONE")
print()

lines = []
while True:
    try:
        line = input()
        if line.strip() == "DONE":
            break
        lines.append(line)
    except EOFError:
        break

raw = "\n".join(lines).strip()

# Coba parse JSON
try:
    sa = json.loads(raw)
    assert sa.get("type") == "service_account", "Bukan service_account JSON!"
    assert "client_email" in sa
    assert "private_key" in sa
    log(f"Service Account: {sa['client_email']}")
    log(f"Project: {sa.get('project_id', '?')}")
except Exception as e:
    print(f"\nERROR: JSON tidak valid — {e}")
    print("Pastikan Anda paste isi lengkap file JSON service account.")
    sys.exit(1)

# Simpan ke file
os.makedirs(os.path.dirname(SA_FILE), exist_ok=True)
with open(SA_FILE, "w") as f:
    json.dump(sa, f, indent=2)
os.chmod(SA_FILE, 0o600)
log(f"Service account disimpan ke: {SA_FILE}")

# Update rclone config
os.makedirs(os.path.dirname(RCLONE_CONF), exist_ok=True)

# Baca config lama, hapus [gdrive] jika ada
conf_lines = []
skip = False
if os.path.exists(RCLONE_CONF):
    for l in open(RCLONE_CONF):
        if l.strip() == "[gdrive]":
            skip = True
        elif l.strip().startswith("[") and l.strip() != "[gdrive]":
            skip = False
        if not skip:
            conf_lines.append(l)

conf_lines.append("\n")
conf_lines.append("[gdrive]\n")
conf_lines.append("type = drive\n")
conf_lines.append("scope = drive\n")
conf_lines.append(f"service_account_file = {SA_FILE}\n")

with open(RCLONE_CONF, "w") as f:
    f.writelines(conf_lines)

log(f"rclone config diperbarui: {RCLONE_CONF}")

# Test koneksi
print()
print("  Testing koneksi ke Google Drive...")
r = subprocess.run(["rclone", "lsd", "gdrive:"], capture_output=True, text=True, timeout=15)
if r.returncode == 0:
    print()
    print("  ✓ Google Drive TERHUBUNG!")
    print()
    # Buat folder backup
    subprocess.run(["rclone", "mkdir", "gdrive:iFix-Pro-Backups"], timeout=15)
    print("  ✓ Folder 'iFix-Pro-Backups' siap di Google Drive")
    print()
    print("=" * 55)
    print("  SETUP SELESAI! Jalankan backup:")
    print()
    print("  IFIX_BACKUP_CONFIG=/workspaces/Ifix-pro/server/ifix_backup_config.json \\")
    print("  python3 /workspaces/Ifix-pro/server/backup_ifix.py")
    print("=" * 55)
else:
    print(f"\n  ERROR: {r.stderr[:300]}")
    print()
    print("  Kemungkinan penyebab:")
    print("  1. Google Drive API belum di-enable di project")
    print("  2. Service account belum di-share ke folder Google Drive")
    print("  3. JSON key tidak valid")
    print()
    print("  Cek langkah 3 & 4 di panduan setup.")
