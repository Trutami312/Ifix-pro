#!/bin/bash
# ═══════════════════════════════════════════════════════
#  iFix Pro - Setup Backup Otomatis ke Google Drive
#  Jalankan: bash setup_backup.sh
# ═══════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()   { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }

CONFIG_FILE="/root/ifix_backup_config.json"
BACKUP_SCRIPT="/root/backup_ifix.py"
RESTORE_SCRIPT="/root/restore_ifix.py"
LOG_FILE="/var/log/ifix_backup.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  iFix Pro - Setup Backup Otomatis ke Google Drive    ${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo ""

# ─── 1. Install rclone ───────────────────────────────────────────────────
echo -e "${BOLD}[1/8] Cek rclone...${NC}"
if command -v rclone &>/dev/null; then
    log "rclone sudah terinstall: $(rclone version | head -1)"
else
    info "Menginstall rclone..."
    curl -fsSL https://rclone.org/install.sh | bash
    log "rclone berhasil diinstall: $(rclone version | head -1)"
fi

# ─── 2. Install Python dependencies ──────────────────────────────────────
echo ""
echo -e "${BOLD}[2/8] Cek Python dependencies...${NC}"
if python3 -c "import requests" 2>/dev/null; then
    log "Python requests sudah terinstall"
else
    info "Menginstall Python requests..."
    pip3 install requests --quiet 2>/dev/null || pip install requests --quiet
    log "Python requests terinstall"
fi

# ─── 3. Copy scripts ke /root ────────────────────────────────────────────
echo ""
echo -e "${BOLD}[3/8] Copy scripts...${NC}"
cp "$SCRIPT_DIR/backup_ifix.py" "$BACKUP_SCRIPT"
chmod +x "$BACKUP_SCRIPT"
log "backup_ifix.py  -> $BACKUP_SCRIPT"

cp "$SCRIPT_DIR/restore_ifix.py" "$RESTORE_SCRIPT"
chmod +x "$RESTORE_SCRIPT"
log "restore_ifix.py -> $RESTORE_SCRIPT"

# ─── 4. Buat log file ────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[4/8] Setup log file...${NC}"
touch "$LOG_FILE"
chmod 644 "$LOG_FILE"
log "Log file: $LOG_FILE"

# ─── 5. Konfigurasi PocketBase credentials ───────────────────────────────
echo ""
echo -e "${BOLD}[5/8] Konfigurasi PocketBase...${NC}"

# Baca PocketBase URL
read -p "  URL PocketBase [http://localhost:8090]: " PB_URL
PB_URL="${PB_URL:-http://localhost:8090}"

read -p "  Email admin PocketBase [admin@ifixpro.com]: " PB_EMAIL
PB_EMAIL="${PB_EMAIL:-admin@ifixpro.com}"

read -sp "  Password admin PocketBase: " PB_PASS
echo ""

if [ -z "$PB_PASS" ]; then
    warn "Password kosong. Edit manual di: $CONFIG_FILE"
fi

# Tulis config JSON
if [ -f "$CONFIG_FILE" ]; then
    # Update existing config
    info "Memperbarui config yang sudah ada..."
    python3 -c "
import json
with open('$CONFIG_FILE') as f:
    cfg = json.load(f)
cfg['pb_url'] = '$PB_URL'
cfg['pb_admin_email'] = '$PB_EMAIL'
cfg['pb_admin_pass'] = '$PB_PASS'
with open('$CONFIG_FILE', 'w') as f:
    json.dump(cfg, f, indent=2)
print('Config updated.')
"
else
    # Buat config baru
    python3 -c "
import json
cfg = {
    'pb_url': '$PB_URL',
    'pb_admin_email': '$PB_EMAIL',
    'pb_admin_pass': '$PB_PASS',
    'rclone_remote': 'gdrive',
    'gdrive_root': 'iFix-Pro-Backups',
    'backup_tmp_dir': '/tmp/ifix_backup',
    'keep_local_days': 7,
    'include_pb_backup': True,
    'include_files': True,
    'max_retries': 3,
    'retry_delay_sec': 10,
    'webhook_url': '',
    'webhook_on_success': False,
    'webhook_on_failure': True,
    'log_file': '/var/log/ifix_backup.log'
}
with open('$CONFIG_FILE', 'w') as f:
    json.dump(cfg, f, indent=2)
print('Config created.')
"
fi
chmod 600 "$CONFIG_FILE"
log "Config tersimpan di: $CONFIG_FILE (mode 600)"

# ─── 6. Webhook notifikasi (opsional) ────────────────────────────────────
echo ""
echo -e "${BOLD}[6/8] Notifikasi webhook (opsional)...${NC}"
echo "  Masukkan URL webhook Discord/Slack untuk notifikasi backup."
echo "  Kosongkan jika tidak butuh notifikasi."
read -p "  Webhook URL: " WEBHOOK_URL

if [ -n "$WEBHOOK_URL" ]; then
    python3 -c "
import json
with open('$CONFIG_FILE') as f:
    cfg = json.load(f)
cfg['webhook_url'] = '$WEBHOOK_URL'
cfg['webhook_on_success'] = True
cfg['webhook_on_failure'] = True
with open('$CONFIG_FILE', 'w') as f:
    json.dump(cfg, f, indent=2)
"
    log "Webhook URL disimpan"
fi

# ─── 7. Konfigurasi rclone Google Drive ──────────────────────────────────
echo ""
echo -e "${BOLD}[7/8] Konfigurasi Google Drive...${NC}"

RCLONE_READY=false
if rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
    log "rclone remote 'gdrive' sudah ada"
    RCLONE_READY=true
else
    warn "rclone remote 'gdrive' BELUM dikonfigurasi."
    echo ""
    echo "┌─────────────────────────────────────────────────────────┐"
    echo "│         LANGKAH KONFIGURASI GOOGLE DRIVE                │"
    echo "├─────────────────────────────────────────────────────────┤"
    echo "│  1. Jalankan: rclone config                             │"
    echo "│  2. Pilih: n  (New remote)                              │"
    echo "│  3. Name: gdrive                                        │"
    echo "│  4. Storage type: cari 'Google Drive'                   │"
    echo "│  5. client_id: (kosongkan, tekan Enter)                 │"
    echo "│  6. client_secret: (kosongkan, tekan Enter)             │"
    echo "│  7. scope: 1  (Full access)                             │"
    echo "│  8. root_folder_id: (kosongkan, tekan Enter)            │"
    echo "│  9. service_account: (kosongkan, tekan Enter)           │"
    echo "│ 10. Edit advanced config? n                             │"
    echo "│ 11. Use auto config?                                    │"
    echo "│     - Jika ada browser: y                               │"
    echo "│     - Jika VPS tanpa browser: n                         │"
    echo "│       → Copy URL ke browser lokal, paste token kembali  │"
    echo "│ 12. Configure as team drive? n                          │"
    echo "│ 13. Konfirmasi: y                                       │"
    echo "└─────────────────────────────────────────────────────────┘"
    echo ""

    read -p "  Jalankan 'rclone config' sekarang? [y/N]: " DO_CONFIG
    if [[ "$DO_CONFIG" =~ ^[Yy]$ ]]; then
        rclone config
        if rclone listremotes | grep -q "^gdrive:"; then
            log "rclone remote 'gdrive' berhasil dikonfigurasi!"
            RCLONE_READY=true
        fi
    else
        warn "Lewati konfigurasi. Jalankan 'rclone config' manual sebelum menjalankan backup."
    fi
fi

# ─── 8. Setup cron job & test ─────────────────────────────────────────────
echo ""
echo -e "${BOLD}[8/8] Setup jadwal backup otomatis...${NC}"

if [ "$RCLONE_READY" = true ]; then
    # Test backup dulu
    read -p "  Jalankan test backup sekarang? [y/N]: " DO_TEST
    if [[ "$DO_TEST" =~ ^[Yy]$ ]]; then
        info "Menjalankan test backup..."
        echo ""
        python3 "$BACKUP_SCRIPT" && log "Test backup berhasil!" || warn "Test backup ada masalah, cek output di atas."
        echo ""
    fi
fi

echo "  Pilih jadwal backup otomatis:"
echo "    1) Setiap hari jam 02:00 malam (recommended)"
echo "    2) Setiap 12 jam (02:00 dan 14:00)"
echo "    3) Setiap hari jam 00:00 tengah malam"
echo "    4) Setiap minggu (Minggu jam 02:00)"
echo "    5) Lewati (atur manual nanti)"
read -p "  Pilih [1-5]: " CRON_CHOICE

CRON_JOB=""
case "$CRON_CHOICE" in
    1) CRON_JOB="0 2 * * * /usr/bin/python3 $BACKUP_SCRIPT >> $LOG_FILE 2>&1" ;;
    2) CRON_JOB="0 2,14 * * * /usr/bin/python3 $BACKUP_SCRIPT >> $LOG_FILE 2>&1" ;;
    3) CRON_JOB="0 0 * * * /usr/bin/python3 $BACKUP_SCRIPT >> $LOG_FILE 2>&1" ;;
    4) CRON_JOB="0 2 * * 0 /usr/bin/python3 $BACKUP_SCRIPT >> $LOG_FILE 2>&1" ;;
    *) warn "Lewati setup cron. Atur manual nanti." ;;
esac

if [ -n "$CRON_JOB" ]; then
    # Hapus cron lama jika ada
    crontab -l 2>/dev/null | grep -v "backup_ifix.py" | crontab - 2>/dev/null || true
    # Tambah cron baru
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    log "Cron job ditambahkan!"
    info "Jadwal: $CRON_JOB"
    info "Cek cron aktif: crontab -l"
fi

# ─── SELESAI ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Setup Selesai!${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo ""
echo "  Struktur backup di Google Drive:"
echo ""
echo "    iFix-Pro-Backups/"
echo "    ├── _fulldb/                    <- Full PocketBase DB backup"
echo "    │   └── auto_20260225_0200.zip"
echo "    ├── _global/                    <- Data owners & users"
echo "    │   └── backup_2026-02-25_0200.zip"
echo "    ├── TokoA_abc12345/             <- Data per-tenant"
echo "    │   └── backup_2026-02-25_0200.zip"
echo "    │       ├── services.json"
echo "    │       ├── sales.json"
echo "    │       ├── products.json"
echo "    │       ├── _files/             <- File attachments"
echo "    │       │   └── products/"
echo "    │       │       └── abc123/image.jpg"
echo "    │       └── summary.json"
echo "    └── TokoB_def67890/"
echo "        └── backup_2026-02-25_0200.zip"
echo ""
echo -e "  ${BOLD}Perintah berguna:${NC}"
echo "    Backup manual     : python3 $BACKUP_SCRIPT"
echo "    List backup Drive : python3 $RESTORE_SCRIPT --list"
echo "    Restore terbaru   : python3 $RESTORE_SCRIPT --restore-latest"
echo "    Restore 1 tenant  : python3 $RESTORE_SCRIPT --restore-tenant NamaToko_abc12345"
echo "    Restore full DB   : python3 $RESTORE_SCRIPT --restore-db"
echo "    Dry-run restore   : python3 $RESTORE_SCRIPT --restore-latest --dry-run"
echo "    Lihat log         : tail -f $LOG_FILE"
echo "    Lihat cron        : crontab -l"
echo "    Edit config       : nano $CONFIG_FILE"
echo "    Lihat isi Drive   : rclone ls gdrive:iFix-Pro-Backups"
echo ""
