#!/usr/bin/env python3
"""
iFix Pro - Restore Data dari Backup Google Drive
=================================================
Restore data tenant dari backup ZIP yang sudah diupload ke Google Drive.

Penggunaan:
  # List semua backup di Google Drive
  python3 restore_ifix.py --list

  # Restore semua tenant dari backup terbaru
  python3 restore_ifix.py --restore-latest

  # Restore satu tenant tertentu
  python3 restore_ifix.py --restore-tenant "NamaToko_abc12345"

  # Restore dari file ZIP lokal
  python3 restore_ifix.py --restore-file /path/to/backup.zip

  # Restore full database backup (PocketBase native)
  python3 restore_ifix.py --restore-db

  # Dry-run (preview tanpa menulis)
  python3 restore_ifix.py --restore-latest --dry-run
"""

import requests
import json
import os
import subprocess
import sys
import zipfile
import argparse
import shutil
from datetime import datetime, timezone

CONFIG_FILE = os.environ.get("IFIX_BACKUP_CONFIG", "/opt/ifix_backup_config.json")

DEFAULT_CONFIG = {
    "pb_url":        "http://localhost:8090",
    "pb_admin_email": "",
    "pb_admin_pass":  "",
    "rclone_remote":  "gdrive",
    "gdrive_root":    "iFix-Pro-Backups",
}


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        log(f"Config tidak ditemukan: {CONFIG_FILE}", "ERROR")
        log("Jalankan backup_ifix.py dulu untuk membuat config.")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        cfg = {**DEFAULT_CONFIG, **json.load(f)}
    return cfg


def pb_admin_login(cfg):
    resp = requests.post(
        f"{cfg['pb_url']}/api/admins/auth-with-password",
        json={"identity": cfg["pb_admin_email"], "password": cfg["pb_admin_pass"]},
        timeout=15
    )
    resp.raise_for_status()
    log(f"Login PocketBase admin OK")
    return resp.json()["token"]


def rclone_list_dirs(cfg, path=""):
    """List direktori di Google Drive."""
    remote_path = f"{cfg['rclone_remote']}:{cfg['gdrive_root']}"
    if path:
        remote_path += f"/{path}"
    try:
        r = subprocess.run(
            ["rclone", "lsd", remote_path],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return []
        dirs = []
        for line in r.stdout.strip().split("\n"):
            if line.strip():
                parts = line.strip().split()
                if len(parts) >= 5:
                    dirs.append(parts[-1])
        return dirs
    except Exception as e:
        log(f"Error listing dirs: {e}", "ERROR")
        return []


def rclone_list_files(cfg, path):
    """List files di Google Drive path."""
    remote_path = f"{cfg['rclone_remote']}:{cfg['gdrive_root']}/{path}"
    try:
        r = subprocess.run(
            ["rclone", "ls", remote_path],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return []
        files = []
        for line in r.stdout.strip().split("\n"):
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                files.append({"size": int(parts[0]), "name": parts[1]})
        return sorted(files, key=lambda x: x["name"], reverse=True)
    except Exception as e:
        log(f"Error listing files: {e}", "ERROR")
        return []


def rclone_download(cfg, remote_path, local_path):
    """Download file dari Google Drive ke lokal."""
    src = f"{cfg['rclone_remote']}:{cfg['gdrive_root']}/{remote_path}"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    try:
        r = subprocess.run(
            ["rclone", "copy", src, os.path.dirname(local_path),
             "--include", os.path.basename(remote_path)],
            capture_output=True, text=True, timeout=300
        )
        return r.returncode == 0
    except Exception as e:
        log(f"Download error: {e}", "ERROR")
        return False


def list_backups(cfg):
    """List semua backup yang tersedia di Google Drive."""
    log("Membaca daftar backup dari Google Drive...")
    tenant_dirs = rclone_list_dirs(cfg)

    print("\n" + "=" * 65)
    print("  DAFTAR BACKUP DI GOOGLE DRIVE")
    print("=" * 65)

    for tdir in sorted(tenant_dirs):
        files = rclone_list_files(cfg, tdir)
        print(f"\n  [{tdir}]")
        if not files:
            print("    (kosong)")
        for f in files[:5]:
            size_mb = f["size"] / 1024 / 1024
            print(f"    {f['name']:45s} {size_mb:8.2f} MB")
        if len(files) > 5:
            print(f"    ... dan {len(files) - 5} file lainnya")

    print("\n" + "=" * 65)


def restore_collection_data(cfg, token, collection, records, owner_id=None, dry_run=False):
    """Restore records ke PocketBase collection."""
    headers = {"Authorization": f"Bearer {token}"}
    created, updated, skipped, errors_count = 0, 0, 0, 0

    for record in records:
        record_id = record.get("id")
        if not record_id:
            skipped += 1
            continue

        if dry_run:
            created += 1
            continue

        # Cek apakah record sudah ada
        try:
            check = requests.get(
                f"{cfg['pb_url']}/api/collections/{collection}/records/{record_id}",
                headers=headers, timeout=10
            )

            # Siapkan data (hapus field system)
            data = {k: v for k, v in record.items()
                    if k not in ("id", "created", "updated", "collectionId", "collectionName", "expand")}

            if check.status_code == 200:
                # Update existing
                resp = requests.patch(
                    f"{cfg['pb_url']}/api/collections/{collection}/records/{record_id}",
                    headers=headers, json=data, timeout=15
                )
                if resp.status_code == 200:
                    updated += 1
                else:
                    errors_count += 1
                    log(f"    Update error {collection}/{record_id}: {resp.status_code}", "WARN")
            else:
                # Create new with specific ID
                data["id"] = record_id
                resp = requests.post(
                    f"{cfg['pb_url']}/api/collections/{collection}/records",
                    headers=headers, json=data, timeout=15
                )
                if resp.status_code == 200:
                    created += 1
                else:
                    errors_count += 1
                    log(f"    Create error {collection}/{record_id}: {resp.status_code}", "WARN")
        except Exception as e:
            errors_count += 1
            log(f"    Exception {collection}/{record_id}: {e}", "ERROR")

    return created, updated, skipped, errors_count


def restore_files(cfg, token, extract_dir, dry_run=False):
    """Restore file attachments dari backup."""
    files_dir = os.path.join(extract_dir, "_files")
    if not os.path.exists(files_dir):
        return 0

    count = 0
    # PocketBase menyimpan file di pb_data/storage/
    # File perlu diupload ulang via API
    for collection in os.listdir(files_dir):
        col_dir = os.path.join(files_dir, collection)
        if not os.path.isdir(col_dir):
            continue
        for record_id in os.listdir(col_dir):
            rec_dir = os.path.join(col_dir, record_id)
            if not os.path.isdir(rec_dir):
                continue
            for fname in os.listdir(rec_dir):
                fpath = os.path.join(rec_dir, fname)
                if dry_run:
                    log(f"    [DRY-RUN] Would upload {collection}/{record_id}/{fname}")
                    count += 1
                    continue
                # Note: File upload via PocketBase requires multipart form
                # This is best-effort; files might need manual upload for some collections
                count += 1
    if count:
        log(f"    {count} file(s) ditemukan di backup (file restore perlu manual upload via API)")
    return count


def restore_from_zip(cfg, zip_path, token, dry_run=False):
    """Restore data dari file ZIP backup."""
    log(f"Membuka backup: {zip_path}")

    extract_dir = "/tmp/ifix_restore_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(extract_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        log(f"Extracted ke: {extract_dir}")

        # Cari summary.json
        summary_path = None
        for root, dirs, files in os.walk(extract_dir):
            if "summary.json" in files:
                summary_path = os.path.join(root, "summary.json")
                break

        data_dir = os.path.dirname(summary_path) if summary_path else extract_dir

        if summary_path:
            with open(summary_path) as f:
                summary = json.load(f)
            log(f"Backup: tenant={summary.get('tenant', '?')}, "
                f"date={summary.get('date', '?')}, "
                f"version={summary.get('backup_version', '1.0')}")
        else:
            log("summary.json tidak ditemukan, mencoba restore semua JSON...", "WARN")

        prefix = "[DRY-RUN] " if dry_run else ""
        total = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}

        # Restore setiap collection
        for fname in os.listdir(data_dir):
            if not fname.endswith(".json") or fname == "summary.json":
                continue
            collection = fname.replace(".json", "")
            fpath = os.path.join(data_dir, fname)

            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)

            records = data.get("records", [])
            if not records:
                continue

            log(f"  {prefix}Restore {collection}: {len(records)} records...")
            c, u, s, e = restore_collection_data(cfg, token, collection, records, dry_run=dry_run)
            total["created"] += c
            total["updated"] += u
            total["skipped"] += s
            total["errors"] += e
            log(f"    -> created={c}, updated={u}, skipped={s}, errors={e}")

        # Restore files
        restore_files(cfg, token, data_dir, dry_run=dry_run)

        log("")
        log("=" * 50)
        log(f"{prefix}RESTORE SELESAI:")
        log(f"  Created: {total['created']}")
        log(f"  Updated: {total['updated']}")
        log(f"  Skipped: {total['skipped']}")
        log(f"  Errors:  {total['errors']}")
        log("=" * 50)

    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def restore_latest(cfg, token, tenant_filter=None, dry_run=False):
    """Restore backup terbaru dari Google Drive."""
    log("Mencari backup terbaru di Google Drive...")
    tenant_dirs = rclone_list_dirs(cfg)

    if tenant_filter:
        tenant_dirs = [d for d in tenant_dirs if tenant_filter in d]
        if not tenant_dirs:
            log(f"Tenant '{tenant_filter}' tidak ditemukan!", "ERROR")
            return

    # Skip system dirs
    tenant_dirs = [d for d in tenant_dirs if not d.startswith("_")]

    for tdir in sorted(tenant_dirs):
        files = rclone_list_files(cfg, tdir)
        zips = [f for f in files if f["name"].endswith(".zip")]

        if not zips:
            log(f"  Skip {tdir}: tidak ada backup ZIP", "WARN")
            continue

        latest = zips[0]  # Already sorted desc
        log(f"  Tenant: {tdir} | Latest: {latest['name']}")

        # Download
        local_dir = f"/tmp/ifix_restore_dl"
        os.makedirs(local_dir, exist_ok=True)
        local_file = os.path.join(local_dir, latest["name"])

        remote = f"{tdir}/{latest['name']}"
        log(f"  Downloading {remote}...")
        src = f"{cfg['rclone_remote']}:{cfg['gdrive_root']}/{tdir}"
        r = subprocess.run(
            ["rclone", "copy", src, local_dir,
             "--include", latest["name"]],
            capture_output=True, text=True, timeout=300
        )
        if r.returncode != 0:
            log(f"  Download gagal: {r.stderr[:200]}", "ERROR")
            continue

        if os.path.exists(local_file):
            restore_from_zip(cfg, local_file, token, dry_run=dry_run)
        else:
            log(f"  File tidak ditemukan setelah download: {local_file}", "ERROR")

    # Cleanup downloads
    shutil.rmtree("/tmp/ifix_restore_dl", ignore_errors=True)


def restore_fulldb(cfg, token, dry_run=False):
    """Restore PocketBase full database backup."""
    log("Mencari full DB backup di Google Drive...")
    files = rclone_list_files(cfg, "_fulldb")
    zips = [f for f in files if f["name"].endswith(".zip")]

    if not zips:
        log("Tidak ada full DB backup di Google Drive!", "ERROR")
        return

    latest = zips[0]
    log(f"Latest full DB backup: {latest['name']} ({latest['size'] // 1024} KB)")

    if dry_run:
        log("[DRY-RUN] Akan download dan restore via PocketBase API")
        return

    # Confirm
    print("\n!!! PERINGATAN !!!")
    print("Restore full database akan MENIMPA semua data yang ada!")
    confirm = input("Ketik 'RESTORE' untuk melanjutkan: ")
    if confirm != "RESTORE":
        log("Dibatalkan.")
        return

    # Download
    local_dir = "/tmp/ifix_restore_fulldb"
    os.makedirs(local_dir, exist_ok=True)

    src = f"{cfg['rclone_remote']}:{cfg['gdrive_root']}/_fulldb"
    r = subprocess.run(
        ["rclone", "copy", src, local_dir, "--include", latest["name"]],
        capture_output=True, text=True, timeout=300
    )
    if r.returncode != 0:
        log(f"Download gagal: {r.stderr[:200]}", "ERROR")
        return

    local_file = os.path.join(local_dir, latest["name"])
    if not os.path.exists(local_file):
        log("File tidak ditemukan setelah download", "ERROR")
        return

    # Upload ke PocketBase backup API
    headers = {"Authorization": f"Bearer {token}"}
    backup_name = latest["name"]

    with open(local_file, "rb") as f:
        resp = requests.post(
            f"{cfg['pb_url']}/api/backups/upload",
            headers=headers,
            files={"file": (backup_name, f)},
            timeout=120
        )

    if resp.status_code in (200, 204):
        log(f"Backup {backup_name} berhasil diupload ke PocketBase")
        log("Untuk melakukan restore, jalankan:")
        log(f"  curl -X POST {cfg['pb_url']}/api/backups/{backup_name}/restore \\")
        log(f"    -H 'Authorization: Bearer <token>'")
    else:
        log(f"Upload backup gagal: {resp.status_code} {resp.text[:200]}", "ERROR")

    shutil.rmtree(local_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="iFix Pro - Restore Data dari Backup Google Drive"
    )
    parser.add_argument("--list", action="store_true",
                        help="List semua backup yang tersedia")
    parser.add_argument("--restore-latest", action="store_true",
                        help="Restore backup terbaru untuk semua tenant")
    parser.add_argument("--restore-tenant", type=str,
                        help="Restore satu tenant tertentu (nama folder)")
    parser.add_argument("--restore-file", type=str,
                        help="Restore dari file ZIP lokal")
    parser.add_argument("--restore-db", action="store_true",
                        help="Restore full PocketBase database backup")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview saja, tidak menulis data")

    args = parser.parse_args()
    cfg = load_config()

    if args.list:
        list_backups(cfg)
        return

    # Login untuk operasi restore
    if not cfg["pb_admin_email"] or not cfg["pb_admin_pass"]:
        log("pb_admin_email / pb_admin_pass belum diisi!", "ERROR")
        sys.exit(1)

    try:
        token = pb_admin_login(cfg)
    except Exception as e:
        log(f"Login gagal: {e}", "ERROR")
        sys.exit(1)

    if args.restore_file:
        if not os.path.exists(args.restore_file):
            log(f"File tidak ditemukan: {args.restore_file}", "ERROR")
            sys.exit(1)
        restore_from_zip(cfg, args.restore_file, token, dry_run=args.dry_run)
    elif args.restore_db:
        restore_fulldb(cfg, token, dry_run=args.dry_run)
    elif args.restore_tenant:
        restore_latest(cfg, token, tenant_filter=args.restore_tenant, dry_run=args.dry_run)
    elif args.restore_latest:
        restore_latest(cfg, token, dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
