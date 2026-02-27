#!/usr/bin/env python3
"""
iFix Pro - Backup Otomatis PocketBase ke Google Drive
=====================================================
Per-tenant backup: setiap owner memiliki folder terpisah di Google Drive
Termasuk: data JSON per-collection, file attachment, dan full DB backup.

Quick Start:
  1. Jalankan pertama kali: python3 /root/backup_ifix.py
     → Akan membuat /root/ifix_backup_config.json
  2. Edit config: nano /root/ifix_backup_config.json
     → Isi pb_admin_email dan pb_admin_pass
  3. Konfigurasi Google Drive: rclone config  (buat remote bernama "gdrive")
  4. Jalankan lagi: python3 /root/backup_ifix.py
"""

import requests
import json
import os
import subprocess
import sys
import zipfile
import time
import traceback
from datetime import datetime, timezone

# ──────────────────────────── CONFIG ────────────────────────────────────────

CONFIG_FILE = os.environ.get("IFIX_BACKUP_CONFIG", "/opt/ifix_backup_config.json")

DEFAULT_CONFIG = {
    "pb_url":            "http://localhost:8090",
    "pb_admin_email":    "",
    "pb_admin_pass":     "",
    "rclone_remote":     "gdrive",
    "gdrive_root":       "iFix-Pro-Backups",
    "backup_tmp_dir":    "/tmp/ifix_backup",
    "keep_local_days":   7,
    "include_pb_backup": True,
    "include_files":     True,
    "max_retries":       3,
    "retry_delay_sec":   10,
    "webhook_url":       "",
    "webhook_on_success": False,
    "webhook_on_failure": True,
    "log_file":          "/tmp/ifix_backup.log",
}

# Collections yang punya field ownerId (per-tenant)
TENANT_COLLECTIONS = [
    "users", "stores", "inventory", "customers",
    "services", "transactions", "sales",
    "suppliers", "brands", "cash_accounts", "cash_flow",
    "debts", "attendance", "leaves", "shifts",
    "payroll", "salarySettings", "purchases",
    "return_purchases", "return_sales",
    "kelengkapan_items", "master_kelengkapan_items",
    "master_qc_functional_items", "qc_functional_items",
    "monthlyBudgets",
]
# Collections global (tidak per-owner)
GLOBAL_COLLECTIONS = ["owners", "Product", "Transaction", "plan_configs", "subscription_config"]

# File fields per collection (type=file di PocketBase)
FILE_FIELDS = {
    "users": ["avatar"],
}

# ──────────────────────────── LOGGING ───────────────────────────────────────

_log_file_handle = None


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    if _log_file_handle:
        try:
            _log_file_handle.write(line + "\n")
            _log_file_handle.flush()
        except Exception:
            pass


def init_log(log_path):
    global _log_file_handle
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        _log_file_handle = open(log_path, "a", encoding="utf-8")
    except Exception as e:
        print(f"[WARN] Tidak bisa buka log file {log_path}: {e}")


# ──────────────────────────── CONFIG ────────────────────────────────────────

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        log(f"Config file dibuat: {CONFIG_FILE}")
        log("  → Edit file tersebut: isi pb_admin_email dan pb_admin_pass")
        log("  → Lalu jalankan ulang script ini.")
        sys.exit(0)
    with open(CONFIG_FILE) as f:
        cfg = {**DEFAULT_CONFIG, **json.load(f)}
    if not cfg["pb_admin_email"] or not cfg["pb_admin_pass"]:
        log(f"pb_admin_email / pb_admin_pass belum diisi di {CONFIG_FILE}", "ERROR")
        sys.exit(1)
    return cfg


# ──────────────────────────── POCKETBASE API ────────────────────────────────

def pb_admin_login(cfg):
    """Login sebagai admin PocketBase dan kembalikan token."""
    resp = requests.post(
        f"{cfg['pb_url']}/api/admins/auth-with-password",
        json={"identity": cfg["pb_admin_email"], "password": cfg["pb_admin_pass"]},
        timeout=15
    )
    resp.raise_for_status()
    log(f"Login PocketBase admin OK ({cfg['pb_admin_email']})")
    return resp.json()["token"]


def pb_get_all(cfg, token, collection, filter_str="", batch=200):
    """Ambil semua record dari collection dengan pagination otomatis."""
    headers = {"Authorization": f"Bearer {token}"}
    records, page = [], 1
    while True:
        params = {"page": page, "perPage": batch, "skipTotal": 1}
        if filter_str:
            params["filter"] = filter_str
        try:
            resp = requests.get(
                f"{cfg['pb_url']}/api/collections/{collection}/records",
                headers=headers, params=params, timeout=30
            )
            if resp.status_code == 404:
                log(f"  Collection '{collection}' tidak ada, skip.", "WARN")
                return []
            resp.raise_for_status()
            items = resp.json().get("items", [])
            records.extend(items)
            if len(items) < batch:
                break
            page += 1
        except Exception as e:
            log(f"  Error fetch {collection} page {page}: {e}", "ERROR")
            break
    return records


def pb_download_file(cfg, token, collection_id, record_id, filename, dest_path):
    """Download satu file attachment dari PocketBase."""
    url = f"{cfg['pb_url']}/api/files/{collection_id}/{record_id}/{filename}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(url, headers=headers, timeout=60, stream=True)
        if resp.status_code != 200:
            return False
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        log(f"    Download file error {filename}: {e}", "WARN")
        return False


def pb_create_backup(cfg, token, out_dir):
    """Full database backup via PocketBase built-in backup API."""
    backup_name = f"auto_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.post(
            f"{cfg['pb_url']}/api/backups",
            headers=headers,
            json={"name": backup_name},
            timeout=120
        )
        if resp.status_code not in (200, 204):
            log(f"  PB backup trigger status {resp.status_code}: {resp.text[:200]}", "WARN")
            return None

        resp2 = requests.get(
            f"{cfg['pb_url']}/api/backups/{backup_name}",
            headers=headers, timeout=300, stream=True
        )
        if resp2.status_code != 200:
            log(f"  PB backup download gagal: {resp2.status_code}", "WARN")
            return None

        os.makedirs(out_dir, exist_ok=True)
        local_path = os.path.join(out_dir, backup_name)
        with open(local_path, "wb") as f:
            for chunk in resp2.iter_content(8192):
                f.write(chunk)

        size_kb = os.path.getsize(local_path) // 1024
        log(f"  PocketBase full backup: {local_path} ({size_kb} KB)")
        return local_path
    except Exception as e:
        log(f"  PB backup error: {e}", "WARN")
        return None


# ──────────────────────────── FILE ATTACHMENT BACKUP ────────────────────────

def backup_files_for_records(cfg, token, collection, records, dest_dir):
    """Download semua file attachment dari records."""
    fields = FILE_FIELDS.get(collection, [])
    if not fields:
        return 0

    count = 0
    files_dir = os.path.join(dest_dir, "_files", collection)

    for record in records:
        record_id = record.get("id", "")
        coll_id = record.get("collectionId", collection)
        for field in fields:
            value = record.get(field)
            if not value:
                continue
            filenames = value if isinstance(value, list) else [value]
            for fname in filenames:
                if not fname or not isinstance(fname, str):
                    continue
                dest = os.path.join(files_dir, record_id, fname)
                if pb_download_file(cfg, token, coll_id, record_id, fname, dest):
                    count += 1
    return count


# ──────────────────────────── RCLONE / GOOGLE DRIVE ─────────────────────────

def check_rclone(cfg):
    """Cek apakah rclone terinstall dan remote sudah dikonfigurasi."""
    try:
        result = subprocess.run(
            ["rclone", "listremotes"],
            capture_output=True, text=True, timeout=10
        )
        remote = f"{cfg['rclone_remote']}:"
        if remote in result.stdout:
            log(f"rclone remote '{cfg['rclone_remote']}' OK")
            return True
        log(f"rclone remote '{cfg['rclone_remote']}' tidak ditemukan!", "ERROR")
        log("Jalankan: rclone config  (buat remote bernama 'gdrive')", "ERROR")
        return False
    except FileNotFoundError:
        log("rclone tidak terinstall! Jalankan: curl https://rclone.org/install.sh | bash", "ERROR")
        return False


def upload_gdrive(cfg, local_path, gdrive_folder):
    """Upload file/folder ke Google Drive via rclone dengan retry + exponential backoff."""
    dest = f"{cfg['rclone_remote']}:{gdrive_folder}"
    max_retries = cfg.get("max_retries", 3)
    delay = cfg.get("retry_delay_sec", 10)

    for attempt in range(1, max_retries + 1):
        try:
            r = subprocess.run(
                ["rclone", "copy", local_path, dest,
                 "--log-level", "NOTICE",
                 "--retries", "3",
                 "--timeout", "120s",
                 "--low-level-retries", "5"],
                capture_output=True, text=True, timeout=300
            )
            if r.returncode == 0:
                log(f"  Upload OK -> {dest}")
                return True
            log(f"  Upload attempt {attempt}/{max_retries} gagal: {r.stderr[:300]}", "WARN")
        except subprocess.TimeoutExpired:
            log(f"  Upload attempt {attempt}/{max_retries} timeout", "WARN")
        except Exception as e:
            log(f"  Upload attempt {attempt}/{max_retries} error: {e}", "WARN")

        if attempt < max_retries:
            wait = delay * attempt
            log(f"  Retry dalam {wait} detik...")
            time.sleep(wait)

    log(f"  Upload GAGAL setelah {max_retries} percobaan: {dest}", "ERROR")
    return False


def verify_upload(cfg, gdrive_folder, expected_file):
    """Verifikasi file sudah ada di Google Drive setelah upload."""
    dest = f"{cfg['rclone_remote']}:{gdrive_folder}"
    try:
        r = subprocess.run(
            ["rclone", "ls", dest],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0 and expected_file in r.stdout:
            return True
    except Exception:
        pass
    return False


# ──────────────────────────── NOTIFICATIONS ─────────────────────────────────

def send_webhook(cfg, title, message, is_error=False):
    """Kirim notifikasi via webhook (support Discord, Slack, atau custom endpoint)."""
    url = cfg.get("webhook_url", "").strip()
    if not url:
        return

    if not is_error and not cfg.get("webhook_on_success", False):
        return
    if is_error and not cfg.get("webhook_on_failure", True):
        return

    color = 0xFF0000 if is_error else 0x00FF00
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Discord format
    payload_discord = {
        "embeds": [{
            "title": title,
            "description": message,
            "color": color,
            "footer": {"text": f"iFix Pro Backup - {ts}"}
        }]
    }

    # Slack format
    payload_slack = {
        "text": f"*{title}*\n{message}"
    }

    for payload in [payload_discord, payload_slack]:
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                log("  Webhook notifikasi terkirim")
                return
        except Exception:
            pass

    # Generic fallback
    try:
        requests.post(url, json={
            "title": title,
            "message": message,
            "is_error": is_error,
            "timestamp": ts
        }, timeout=10)
    except Exception:
        log("  Webhook gagal dikirim", "WARN")


# ──────────────────────────── TENANT BACKUP ─────────────────────────────────

def backup_tenant(cfg, token, owner, date_str):
    """Backup semua data milik satu tenant/owner ke ZIP."""
    oid = owner["id"]
    oname = owner.get("name") or owner.get("storeName") or oid
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in oname).strip().replace(" ", "_")
    folder_key = f"{safe}_{oid[:8]}"

    tenant_dir = os.path.join(cfg["backup_tmp_dir"], folder_key, date_str)
    os.makedirs(tenant_dir, exist_ok=True)
    log(f"  Backup tenant: {oname} ({oid})")

    summary = {
        "tenant": oname,
        "owner_id": oid,
        "date": date_str,
        "collections": {},
        "files_count": 0,
        "backup_version": "2.0",
    }

    total_files = 0

    for col in TENANT_COLLECTIONS:
        records = pb_get_all(cfg, token, col, filter_str=f'ownerId = "{oid}"')
        out_path = os.path.join(tenant_dir, f"{col}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({
                "collection": col,
                "owner_id": oid,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "count": len(records),
                "records": records
            }, f, ensure_ascii=False, indent=2)
        summary["collections"][col] = len(records)
        log(f"    {col}: {len(records)} records")

        # Download file attachments jika ada
        if cfg.get("include_files", True) and records:
            fc = backup_files_for_records(cfg, token, col, records, tenant_dir)
            if fc:
                log(f"    {col}: {fc} file(s) downloaded")
                total_files += fc

    summary["files_count"] = total_files

    with open(os.path.join(tenant_dir, "summary.json"), "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # Buat ZIP termasuk semua data + files
    zip_name = f"backup_{date_str}.zip"
    zip_path = os.path.join(cfg["backup_tmp_dir"], folder_key, zip_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(tenant_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                arc_name = os.path.relpath(full_path, os.path.dirname(tenant_dir))
                zf.write(full_path, arc_name)

    size_kb = os.path.getsize(zip_path) // 1024
    log(f"    ZIP: {zip_name} ({size_kb} KB, {total_files} files)")
    return folder_key, zip_path, zip_name, summary


# ──────────────────────────── CLEANUP ───────────────────────────────────────

def cleanup_old(tmp_dir, keep_days):
    """Hapus file backup lokal yang sudah lewat batas retensi."""
    cutoff = time.time() - keep_days * 86400
    n = 0
    for root, dirs, files in os.walk(tmp_dir, topdown=False):
        for fname in files:
            p = os.path.join(root, fname)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
                    n += 1
            except Exception:
                pass
        for d in dirs:
            dp = os.path.join(root, d)
            try:
                if not os.listdir(dp):
                    os.rmdir(dp)
            except Exception:
                pass
    if n:
        log(f"Cleanup: hapus {n} file lokal lama (>{keep_days} hari)")


# ──────────────────────────── MAIN ──────────────────────────────────────────

def main():
    start_time = time.time()

    log("=" * 60)
    log("iFix Pro - Backup Otomatis ke Google Drive v2.0")
    log("=" * 60)

    cfg = load_config()
    init_log(cfg.get("log_file", "/var/log/ifix_backup.log"))

    if not check_rclone(cfg):
        send_webhook(cfg, "Backup Gagal", "rclone tidak tersedia atau belum dikonfigurasi.", is_error=True)
        sys.exit(1)

    try:
        token = pb_admin_login(cfg)
    except Exception as e:
        log(f"Login PocketBase gagal: {e}", "ERROR")
        send_webhook(cfg, "Backup Gagal", f"Login PocketBase gagal: {e}", is_error=True)
        sys.exit(1)

    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    os.makedirs(cfg["backup_tmp_dir"], exist_ok=True)

    errors = []
    results = []

    # ── 1. Full DB backup via PocketBase API ──
    if cfg.get("include_pb_backup"):
        log("")
        log("--- Full Database Backup ---")
        pb_dir = os.path.join(cfg["backup_tmp_dir"], "_fulldb")
        pb_zip = pb_create_backup(cfg, token, pb_dir)
        if pb_zip:
            ok = upload_gdrive(cfg, pb_zip, f"{cfg['gdrive_root']}/_fulldb")
            if not ok:
                errors.append("Upload full DB backup gagal")
        else:
            errors.append("Pembuatan full DB backup gagal")

    # ── 2. Global collections (owners, users) ──
    log("")
    log("--- Global Collections ---")
    global_dir = os.path.join(cfg["backup_tmp_dir"], "_global", date_str)
    global_zip_path = os.path.join(cfg["backup_tmp_dir"], "_global", f"backup_{date_str}.zip")
    os.makedirs(global_dir, exist_ok=True)

    with zipfile.ZipFile(global_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for col in GLOBAL_COLLECTIONS:
            records = pb_get_all(cfg, token, col)
            fpath = os.path.join(global_dir, f"{col}.json")
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump({
                    "collection": col,
                    "count": len(records),
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "records": records
                }, f, ensure_ascii=False, indent=2)
            zf.write(fpath, os.path.join(date_str, f"{col}.json"))
            log(f"  [global] {col}: {len(records)} records")

            # Download file attachments global collections
            if cfg.get("include_files", True) and records:
                fc = backup_files_for_records(cfg, token, col, records, global_dir)
                if fc:
                    log(f"  [global] {col}: {fc} file(s)")
                    files_dir = os.path.join(global_dir, "_files")
                    if os.path.exists(files_dir):
                        for froot, fdirs, ffiles in os.walk(files_dir):
                            for fn in ffiles:
                                full_p = os.path.join(froot, fn)
                                arc = os.path.relpath(full_p, global_dir)
                                zf.write(full_p, os.path.join(date_str, arc))

    ok = upload_gdrive(cfg, global_zip_path, f"{cfg['gdrive_root']}/_global")
    if not ok:
        errors.append("Upload global backup gagal")

    # ── 3. Per-tenant backup ──
    log("")
    log("--- Per-Tenant Backup ---")
    owners = pb_get_all(cfg, token, "owners")
    log(f"Total {len(owners)} tenant ditemukan")

    for owner in owners:
        oname = owner.get("name") or owner.get("storeName") or owner["id"]
        try:
            folder_key, zip_path, zip_name, summary = backup_tenant(cfg, token, owner, date_str)
            gdrive_dest = f"{cfg['gdrive_root']}/{folder_key}"
            ok = upload_gdrive(cfg, zip_path, gdrive_dest)

            if ok:
                verified = verify_upload(cfg, gdrive_dest, zip_name)
                if not verified:
                    log(f"  Upload verifikasi gagal untuk {oname}", "WARN")

            results.append({**summary, "upload": "OK" if ok else "FAILED"})
            if not ok:
                errors.append(f"Upload tenant '{oname}' gagal")
        except Exception as e:
            log(f"  ERROR backup tenant {oname}: {e}", "ERROR")
            log(traceback.format_exc(), "ERROR")
            errors.append(f"Backup tenant '{oname}' error: {e}")
            results.append({
                "tenant": oname,
                "owner_id": owner["id"],
                "upload": "ERROR",
                "error": str(e),
                "collections": {}
            })

    # ── 4. Cleanup ──
    cleanup_old(cfg["backup_tmp_dir"], cfg["keep_local_days"])

    # ── 5. Summary ──
    elapsed = time.time() - start_time
    elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

    log("")
    log("=" * 60)
    log("RINGKASAN BACKUP:")
    log("-" * 60)
    for r in results:
        st = "[OK]" if r.get("upload") == "OK" else "[FAIL]"
        cols = r.get("collections", {})
        tot = sum(v for v in cols.values() if isinstance(v, int))
        fc = r.get("files_count", 0)
        tenant = r.get("tenant", "?")
        log(f"  {st:6s} {tenant:30s} {tot:5d} records  {fc:3d} files")
    log("-" * 60)
    log(f"Durasi: {elapsed_str} | Errors: {len(errors)}")
    log("=" * 60)

    # ── 6. Webhook ──
    if errors:
        error_list = "\n".join(f"- {e}" for e in errors)
        send_webhook(
            cfg,
            f"Backup Selesai dengan {len(errors)} Error",
            f"Tanggal: {date_str}\nDurasi: {elapsed_str}\n"
            f"Tenant: {len(results)}\n\nErrors:\n{error_list}",
            is_error=True
        )
    else:
        total_records = sum(
            sum(v for v in r.get("collections", {}).values() if isinstance(v, int))
            for r in results
        )
        total_files = sum(r.get("files_count", 0) for r in results)
        send_webhook(
            cfg,
            "Backup Berhasil",
            f"Tanggal: {date_str}\nDurasi: {elapsed_str}\n"
            f"Tenant: {len(results)}\nTotal Records: {total_records}\n"
            f"Total Files: {total_files}",
            is_error=False
        )

    log("Selesai!")
    if errors:
        sys.exit(2)


if __name__ == "__main__":
    main()
