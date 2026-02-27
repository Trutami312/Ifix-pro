# iFix Pro - Backup & Restore System

Sistem backup otomatis untuk semua data tenant PocketBase ke Google Drive.

## Fitur

- **Backup per-tenant** — Setiap owner memiliki folder terpisah di Google Drive
- **Full database backup** — Menggunakan PocketBase built-in backup API
- **File attachment backup** — Download foto/gambar dari semua collection
- **Auto retry** — Upload gagal akan dicoba ulang dengan exponential backoff
- **Verifikasi upload** — Memastikan file sudah ada di Google Drive setelah upload
- **Webhook notifikasi** — Kirim alert ke Discord/Slack saat backup gagal/berhasil
- **Restore tool** — Script untuk mengembalikan data dari backup
- **Cron scheduling** — Backup otomatis harian/mingguan

## Quick Start

```bash
# 1. Jalankan setup (install rclone, konfigurasi Google Drive, set jadwal)
cd server
bash setup_backup.sh

# 2. Atau manual:
python3 backup_ifix.py     # jalankan backup
python3 restore_ifix.py --list   # lihat daftar backup
```

## File Structure

```
server/
├── backup_ifix.py       # Script backup utama
├── restore_ifix.py      # Script restore data
├── setup_backup.sh      # Setup wizard interaktif
└── BACKUP.md            # Dokumentasi ini
```

## Konfigurasi

Config disimpan di `/root/ifix_backup_config.json`:

```json
{
  "pb_url": "http://localhost:8090",
  "pb_admin_email": "admin@ifixpro.com",
  "pb_admin_pass": "password_anda",
  "rclone_remote": "gdrive",
  "gdrive_root": "iFix-Pro-Backups",
  "backup_tmp_dir": "/tmp/ifix_backup",
  "keep_local_days": 7,
  "include_pb_backup": true,
  "include_files": true,
  "max_retries": 3,
  "retry_delay_sec": 10,
  "webhook_url": "",
  "webhook_on_success": false,
  "webhook_on_failure": true,
  "log_file": "/var/log/ifix_backup.log"
}
```

| Parameter | Deskripsi |
|-----------|-----------|
| `pb_url` | URL PocketBase server |
| `pb_admin_email` | Email admin PocketBase |
| `pb_admin_pass` | Password admin PocketBase |
| `rclone_remote` | Nama remote rclone (default: `gdrive`) |
| `gdrive_root` | Folder root di Google Drive |
| `backup_tmp_dir` | Folder temporary untuk backup lokal |
| `keep_local_days` | Berapa hari backup lokal disimpan |
| `include_pb_backup` | Backup full database PocketBase (true/false) |
| `include_files` | Backup file attachment/foto (true/false) |
| `max_retries` | Jumlah retry upload jika gagal |
| `retry_delay_sec` | Delay antar retry (detik) |
| `webhook_url` | URL webhook Discord/Slack |
| `webhook_on_success` | Kirim notifikasi saat berhasil |
| `webhook_on_failure` | Kirim notifikasi saat gagal |

## Struktur Backup di Google Drive

```
iFix-Pro-Backups/
├── _fulldb/                           # Full PocketBase database
│   └── auto_20260225_0200.zip
├── _global/                           # Data global (owners, users)
│   └── backup_2026-02-25_0200.zip
│       ├── owners.json
│       └── users.json
├── TokoABC_abc12345/                  # Data per-tenant
│   └── backup_2026-02-25_0200.zip
│       ├── services.json
│       ├── sales.json
│       ├── salesItems.json
│       ├── customers.json
│       ├── products.json
│       ├── parts.json
│       ├── stores.json
│       ├── cashAccounts.json
│       ├── cashTransactions.json
│       ├── expenses.json
│       ├── usedParts.json
│       ├── _files/                    # File attachments
│       │   ├── products/
│       │   │   └── <record_id>/image.jpg
│       │   └── services/
│       │       └── <record_id>/photo.jpg
│       └── summary.json
└── TokoXYZ_def67890/
    └── ...
```

## Backup Commands

```bash
# Jalankan backup manual
python3 /root/backup_ifix.py

# Lihat log backup
tail -f /var/log/ifix_backup.log

# Lihat cron yang aktif
crontab -l

# Lihat isi backup di Google Drive
rclone ls gdrive:iFix-Pro-Backups
rclone tree gdrive:iFix-Pro-Backups --max-depth 2
```

## Restore Commands

```bash
# List semua backup di Google Drive
python3 /root/restore_ifix.py --list

# Restore semua tenant dari backup terbaru
python3 /root/restore_ifix.py --restore-latest

# Preview restore tanpa menulis data (dry-run)
python3 /root/restore_ifix.py --restore-latest --dry-run

# Restore satu tenant tertentu
python3 /root/restore_ifix.py --restore-tenant "TokoABC_abc12345"

# Restore dari file ZIP lokal
python3 /root/restore_ifix.py --restore-file /path/to/backup.zip

# Restore full PocketBase database
python3 /root/restore_ifix.py --restore-db
```

## Webhook Notifikasi

Mendukung Discord dan Slack webhook:

### Discord
1. Buka Discord Server Settings → Integrations → Webhooks
2. Buat webhook baru, copy URL
3. Paste ke `webhook_url` di config

### Slack
1. Buat Incoming Webhook di Slack App
2. Copy webhook URL
3. Paste ke `webhook_url` di config

## Troubleshooting

### rclone remote 'gdrive' tidak ditemukan
```bash
rclone config
# Ikuti wizard untuk membuat remote 'gdrive'
```

### Login PocketBase gagal
- Pastikan `pb_url`, `pb_admin_email`, `pb_admin_pass` sudah benar di config
- Pastikan PocketBase server berjalan

### Upload gagal
- Cek koneksi internet
- Cek kuota Google Drive
- Cek log: `tail -50 /var/log/ifix_backup.log`
- Coba manual: `rclone ls gdrive:`

### Backup terlalu besar
- Set `include_files` ke `false` untuk skip file attachment
- Kurangi `keep_local_days` untuk membersihkan backup lokal lebih cepat
