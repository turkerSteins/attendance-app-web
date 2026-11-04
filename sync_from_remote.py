"""
Uzak (93.177.102.97) MSSQL sunucusundaki verileri yerel (localhost) MSSQL veritabanına aktaran senkronizasyon scripti.
"""

import os
import sys
import pyodbc
from dotenv import load_dotenv
from database import get_best_driver

load_dotenv(override=True)

# ==============================================================================
# BAĞLANTI AYARLARI
# ==============================================================================

# 1. UZAK KAYNAK (REMOTE / SOURCE) VERİTABANI
REMOTE_CONFIG = {
    "server": "93.177.102.97",
    "database": "Personnel_Attendance_Control",
    "use_windows_auth": False,
    "username": "Mfd",
    "password": "Mcsfd.2018",
    "trust_cert": "yes"
}

# 2. YEREL HEDEF (LOCAL / TARGET) VERİTABANI (.env ayarlarınızı kullanır)
LOCAL_CONFIG = {
    "server": os.getenv("SERVER", "localhost").strip(),
    "database": os.getenv("DATABASE", "Personnel_Attendance_Control").strip(),
    "use_windows_auth": os.getenv("USE_WINDOWS_AUTH", "yes").strip().lower() in ("yes", "true", "1"),
    "username": (os.getenv("DB_USER") or os.getenv("DB_USERNAME") or os.getenv("USERNAME") or "sa").strip(),
    "password": os.getenv("PASSWORD", "").strip(),
    "trust_cert": os.getenv("TRUST_SERVER_CERTIFICATE", "yes").strip()
}

# Aktarılacak tablolar (Foreign key sırasına göre)
TABLES_TO_SYNC = [
    "Locations",
    "Users",
    "Terminals",
    "FieldAttendanceLogs"
]

def build_conn_str(config: dict, driver: str) -> str:
    conn_str = f"DRIVER={{{driver}}};SERVER={config['server']};DATABASE={config['database']};"
    if config.get("use_windows_auth"):
        conn_str += "Trusted_Connection=yes;"
    else:
        conn_str += f"UID={config['username']};PWD={config['password']};"
    
    if "ODBC Driver" in driver:
        conn_str += f"TrustServerCertificate={config.get('trust_cert', 'yes')};"
    return conn_str

def get_table_columns(cursor, table_name: str) -> list[str]:
    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = ? 
        ORDER BY ORDINAL_POSITION
    """, (table_name,))
    return [row[0] for row in cursor.fetchall()]

def has_identity_column(cursor, table_name: str) -> bool:
    cursor.execute("""
        SELECT 1 FROM sys.columns 
        WHERE object_id = OBJECT_ID(?) AND is_identity = 1
    """, (table_name,))
    return cursor.fetchone() is not None

def table_exists(cursor, table_name: str) -> bool:
    cursor.execute("""
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?
    """, (table_name,))
    return cursor.fetchone() is not None

def main():
    driver = get_best_driver()
    print("=" * 65)
    print(" MSSQL VERİ SENKRONİZASYON ARACI (UZAK -> YEREL)")
    print("=" * 65)
    print(f"Kullanılan ODBC Sürücüsü: {driver}")
    print(f"Kaynak (Uzak) : {REMOTE_CONFIG['server']} -> {REMOTE_CONFIG['database']}")
    print(f"Hedef  (Yerel): {LOCAL_CONFIG['server']} -> {LOCAL_CONFIG['database']}")
    print("=" * 65)

    # 1. Uzak Bağlantıyı Test Et
    print("\n[1/4] Uzak sunucuya (93.177.102.97) bağlanılıyor...")
    try:
        remote_conn_str = build_conn_str(REMOTE_CONFIG, driver)
        remote_conn = pyodbc.connect(remote_conn_str, timeout=15)
        remote_cursor = remote_conn.cursor()
        print("  -> Uzak veritabanı bağlantısı BAŞARILI.")
    except Exception as e:
        print(f"\n[HATA] Uzak sunucuya bağlanılamadı:\n{e}")
        print("\nOlası Nedenler:")
        print(" - Kullanıcı adı veya şifre hatalı olabilir.")
        print(" - VPN veya şirket ağı gerekiyor olabilir.")
        print(" - 93.177.102.97 sunucusunun 1433 portu kapalı veya erişilemez olabilir.")
        sys.exit(1)

    # 2. Yerel Bağlantıyı Test Et
    print("\n[2/4] Yerel sunucuya (localhost) bağlanılıyor...")
    try:
        local_conn_str = build_conn_str(LOCAL_CONFIG, driver)
        local_conn = pyodbc.connect(local_conn_str, timeout=10)
        local_cursor = local_conn.cursor()
        print("  -> Yerel veritabanı bağlantısı BAŞARILI.")
    except Exception as e:
        print(f"\n[HATA] Yerel (localhost) sunucuya bağlanılamadı:\n{e}")
        print("\nOlası Nedenler:")
        print(" - Yerel SQL Server servisi çalışmıyor olabilir.")
        print(" - LOCAL_CONFIG içindeki 'use_windows_auth' veya kullanıcı bilgileri uyumsuz olabilir.")
        print(" - Hedef veritabanı (Personnel_Attendance_Control) henüz oluşturulmamış olabilir.")
        remote_conn.close()
        sys.exit(1)

    # 3. Yerel Tabloları Kontrol Et ve Temizleme Onayı
    print("\n[3/4] Hedef tablolar kontrol ediliyor...")
    for table in reversed(TABLES_TO_SYNC):
        if not table_exists(local_cursor, table):
            print(f"[UYARI] Yerel veritabanında '{table}' tablosu bulunamadı!")
            print("Lütfen önce 'python init_db.py' komutunu çalıştırarak yerel tabloları oluşturun.")
            remote_conn.close()
            local_conn.close()
            sys.exit(1)

    auto_confirm = "--yes" in sys.argv or "-y" in sys.argv
    if not auto_confirm:
        print("\n⚠️  DİKKAT: Aktarım öncesinde yerel veritabanındaki çakışmaları önlemek için")
        print("   yerel tablolardaki mevcut veriler (varsayılan admin vb.) silinip uzaktaki veriler yazılacaktır.")
        confirm = input("Devam etmek istiyor musunuz? (E/H) [Varsayılan: E]: ").strip().upper()
        if confirm not in ("", "E", "EVET", "Y", "YES"):
            print("İşlem kullanıcı tarafından iptal edildi.")
            remote_conn.close()
            local_conn.close()
            sys.exit(0)

    # Yerel tabloları ilişkili sıraya göre temizle (Önce child tablolar)
    print("\nYerel tablolardaki eski veriler temizleniyor...")
    for table in reversed(TABLES_TO_SYNC):
        try:
            local_cursor.execute(f"DELETE FROM [{table}];")
            local_conn.commit()
            print(f"  - [{table}] tablosu boşaltıldı.")
        except Exception as e:
            print(f"  [UYARI] [{table}] temizlenirken hata: {e}")

    # 4. Verileri Çek ve Yerel Tabloya Aktar
    print("\n[4/4] Veri aktarımı başlıyor...")
    
    total_migrated = 0

    for table in TABLES_TO_SYNC:
        print(f"\n---> [{table}] aktarılıyor...")
        
        # Kolonları belirle
        remote_cols = get_table_columns(remote_cursor, table)
        local_cols = get_table_columns(local_cursor, table)
        common_cols = [c for c in remote_cols if c in local_cols]

        if not common_cols:
            print(f"  [ATLANDI] Ortak kolon bulunamadı.")
            continue

        cols_str = ", ".join(f"[{c}]" for c in common_cols)
        placeholders = ", ".join("?" for _ in common_cols)

        # Uzaktan verileri oku
        remote_cursor.execute(f"SELECT {cols_str} FROM [{table}];")
        rows = remote_cursor.fetchall()
        row_count = len(rows)
        print(f"  - Uzak sunucudan {row_count} adet kayıt okundu.")

        if row_count == 0:
            print(f"  - Aktarılacak veri yok.")
            continue

        # Yerel tabloya yaz
        has_id = has_identity_column(local_cursor, table)
        if has_id:
            local_cursor.execute(f"SET IDENTITY_INSERT [{table}] ON;")

        insert_sql = f"INSERT INTO [{table}] ({cols_str}) VALUES ({placeholders});"

        batch_size = 500
        converted_rows = [tuple(row) for row in rows]

        try:
            for i in range(0, row_count, batch_size):
                batch = converted_rows[i:i + batch_size]
                local_cursor.executemany(insert_sql, batch)
                local_conn.commit()
            
            if has_id:
                local_cursor.execute(f"SET IDENTITY_INSERT [{table}] OFF;")
                local_conn.commit()

            print(f"  -> BAŞARILI: {row_count} kayıt [{table}] tablosuna aktarıldı.")
            total_migrated += row_count
        except Exception as e:
            local_conn.rollback()
            if has_id:
                try:
                    local_cursor.execute(f"SET IDENTITY_INSERT [{table}] OFF;")
                except Exception:
                    pass
            print(f"  [HATA] [{table}] aktarılırken hata oluştu:\n{e}")
            break

    # Bağlantıları kapat
    remote_conn.close()
    local_conn.close()

    print("\n" + "=" * 65)
    print(f" SENKRONİZASYON TAMAMLANDI! Toplam {total_migrated} kayıt aktarıldı.")
    print("=" * 65)

if __name__ == "__main__":
    main()
