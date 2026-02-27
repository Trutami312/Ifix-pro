#!/bin/bash
# iFix Pro - Setup Google Drive (rclone)
# Jalankan: bash /workspaces/Ifix-pro/server/gdrive_setup.sh

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║   iFix Pro - Setup Google Drive untuk Backup        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Cek rclone
if ! command -v rclone &>/dev/null; then
    echo -e "${YELLOW}Installing rclone...${NC}"
    curl -fsSL https://rclone.org/install.sh | sudo bash
fi
echo -e "${GREEN}[OK]${NC} rclone $(rclone version | head -1 | awk '{print $2}')"

# Cek apakah gdrive sudah ada
if rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
    echo -e "${GREEN}[OK]${NC} rclone remote 'gdrive' sudah dikonfigurasi!"
    echo ""
    echo "Test koneksi..."
    if rclone lsd gdrive: --max-depth 1 2>/dev/null; then
        echo -e "${GREEN}Google Drive terhubung!${NC}"
    fi
    echo ""
    echo "Lewati setup (sudah ada). Langsung jalankan backup:"
    echo "  sudo python3 /root/backup_ifix.py"
    exit 0
fi

echo ""
echo -e "${CYAN}Ada 2 cara menghubungkan Google Drive:${NC}"
echo ""
echo "  [1] OAuth via browser (mudah, cocok jika ada akses browser)"
echo "  [2] Service Account JSON (untuk server/VPS, tidak perlu browser)"
echo ""
read -p "Pilih [1/2]: " CHOICE

if [[ "$CHOICE" == "2" ]]; then
    echo ""
    echo -e "${BOLD}== Service Account (Rekomendasi untuk Server) ==${NC}"
    echo ""
    echo "Langkah membuat Service Account di Google Cloud:"
    echo ""
    echo "  1. Buka: https://console.cloud.google.com/"
    echo "  2. Buat Project baru (atau pilih yang ada)"
    echo "  3. APIs & Services → Enable APIs → cari & enable:"
    echo "       'Google Drive API'"
    echo "  4. APIs & Services → Credentials → "+ Create Credentials""
    echo "       → pilih 'Service Account'"
    echo "  5. Isi nama: ifix-backup → Create"
    echo "  6. Klik service account yang baru → Keys tab"
    echo "       → Add Key → Create new key → JSON → Create"
    echo "  7. File JSON akan terdownload ke komputer Anda"
    echo "  8. Share folder Google Drive 'iFix-Pro-Backups' ke email service account"
    echo "     (email berakhiran @...iam.gserviceaccount.com)"
    echo ""
    read -p "Paste path file JSON key (atau drag & drop ke terminal): " SA_FILE
    SA_FILE="${SA_FILE//\'/}"  # remove quotes if any
    SA_FILE="${SA_FILE// /}"   # remove spaces

    if [[ ! -f "$SA_FILE" ]]; then
        echo "File tidak ditemukan: $SA_FILE"
        exit 1
    fi

    # Buat rclone config untuk service account
    mkdir -p ~/.config/rclone
    cat > ~/.config/rclone/rclone.conf << EOF
[gdrive]
type = drive
scope = drive
service_account_file = $SA_FILE
EOF
    echo ""
    echo "Testing koneksi..."
    if rclone lsd gdrive: 2>/dev/null; then
        echo -e "${GREEN}Google Drive terhubung via Service Account!${NC}"
    else
        echo "Membuat folder root..."
        rclone mkdir gdrive:iFix-Pro-Backups
        echo -e "${GREEN}Folder 'iFix-Pro-Backups' dibuat di Google Drive!${NC}"
    fi

else
    echo ""
    echo -e "${BOLD}== OAuth via Browser ==${NC}"
    echo ""
    echo "PENTING: Cara ini butuh Anda membuka link di browser."
    echo ""
    echo -e "${YELLOW}Jalankan command berikut di terminal ini:${NC}"
    echo ""
    echo -e "  ${BOLD}rclone config${NC}"
    echo ""
    echo "Ikuti langkah:"
    echo "  1. Ketik: n  (New remote)"
    echo "  2. name> gdrive"
    echo "  3. Storage> (ketik nomor untuk Google Drive, biasanya 18 atau 20)"
    echo "  4. client_id>  [Enter - kosongkan]"
    echo "  5. client_secret>  [Enter - kosongkan]"
    echo "  6. scope> 1  (full access)"
    echo "  7. root_folder_id>  [Enter - kosongkan]"
    echo "  8. service_account_file>  [Enter - kosongkan]"
    echo "  9. Edit advanced config? n"
    echo " 10. Use web browser to automatically authenticate? n  ← PENTING! pilih n (headless)"
    echo "     → rclone akan tampilkan URL panjang"
    echo "     → Copy URL tersebut, buka di browser di komputer Anda"
    echo "     → Login dengan akun Google"
    echo "     → Copy token yang muncul, paste kembali ke terminal"
    echo " 11. Configure this as a Shared Drive? n"
    echo " 12. Konfirmasi: y"
    echo " 13. Ketik: q  (quit)"
    echo ""
    echo -e "${YELLOW}Jalankan sekarang:${NC}"
    echo ""
    echo "  rclone config"
    echo ""
    read -p "Tekan Enter setelah selesai rclone config..." 

    if rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
        echo -e "${GREEN}Remote 'gdrive' berhasil dikonfigurasi!${NC}"
    else
        echo "Remote 'gdrive' belum terdeteksi. Cek kembali konfigurasi."
        exit 1
    fi
fi

# Test dan buat folder
echo ""
echo "Membuat folder iFix-Pro-Backups di Google Drive..."
rclone mkdir gdrive:iFix-Pro-Backups 2>/dev/null || true
echo -e "${GREEN}[OK]${NC} Folder siap!"

# Setup cron
echo ""
echo -e "${BOLD}Setup jadwal backup otomatis:${NC}"
echo "  1) Setiap hari jam 02:00 (recommended)"
echo "  2) Setiap 12 jam (02:00 & 14:00)"
echo "  3) Setiap minggu Minggu jam 02:00"
echo "  4) Lewati"
read -p "Pilih [1-4]: " CRON_CHOICE

CRON_JOB=""
case "$CRON_CHOICE" in
    1) CRON_JOB="0 2 * * * /usr/bin/python3 /root/backup_ifix.py >> /var/log/ifix_backup.log 2>&1" ;;
    2) CRON_JOB="0 2,14 * * * /usr/bin/python3 /root/backup_ifix.py >> /var/log/ifix_backup.log 2>&1" ;;
    3) CRON_JOB="0 2 * * 0 /usr/bin/python3 /root/backup_ifix.py >> /var/log/ifix_backup.log 2>&1" ;;
    *) echo "Lewati cron." ;;
esac

if [[ -n "$CRON_JOB" ]]; then
    crontab -l 2>/dev/null | grep -v "backup_ifix.py" | crontab - 2>/dev/null || true
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo -e "${GREEN}[OK]${NC} Cron job ditambahkan: $CRON_JOB"
fi

# Test backup
echo ""
read -p "Jalankan test backup sekarang? [y/N]: " DO_TEST
if [[ "$DO_TEST" =~ ^[Yy]$ ]]; then
    echo ""
    sudo python3 /root/backup_ifix.py
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  Setup Google Drive Selesai!         ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""
echo "  Backup manual    : sudo python3 /root/backup_ifix.py"
echo "  Lihat log        : tail -f /var/log/ifix_backup.log"
echo "  Lihat isi Drive  : rclone ls gdrive:iFix-Pro-Backups"
echo "  Cek cron         : crontab -l"
echo ""
