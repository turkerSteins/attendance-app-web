import os
import pyodbc
from contextlib import contextmanager
from dotenv import load_dotenv

# .env dosyasındaki ortam değişkenlerini yükle (override=True: Windows sistem değişkenlerini geçersiz kılar)
load_dotenv(override=True)

DB_SERVER = os.getenv("SERVER", "localhost").strip()
DB_DATABASE = os.getenv("DATABASE", "AttendanceDB").strip()
DB_USERNAME = (os.getenv("DB_USER") or os.getenv("DB_USERNAME") or os.getenv("USERNAME") or "sa").strip()
DB_PASSWORD = os.getenv("PASSWORD", "").strip()
DB_TRUST_CERT = os.getenv("TRUST_SERVER_CERTIFICATE", "yes").strip()
USE_WINDOWS_AUTH = os.getenv("USE_WINDOWS_AUTH", "no").strip().lower() in ("yes", "true", "1")

def get_best_driver() -> str:
    """
    Sistemde yüklü olan MSSQL ODBC sürücüsünü otomatik tespit eder.
    """
    installed_drivers = pyodbc.drivers()
    env_driver = os.getenv("DRIVER")
    
    # 1. Kullanıcı .env içinde tanımlamışsa ve sistemde yüklüyse onu kullan
    if env_driver and env_driver in installed_drivers:
        return env_driver
    
    # 2. Sistemde yüklü olan sürücülerden en uygun olanını seç
    candidates = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server"
    ]
    
    for candidate in candidates:
        if candidate in installed_drivers:
            return candidate
            
    # Sürücü bulunamadıysa varsayılan 'SQL Server' döndür
    return env_driver or "SQL Server"

def build_connection_string() -> str:
    """
    MSSQL pyodbc bağlantı dizesini dinamik olarak oluşturur.
    Windows Authentication (Trusted_Connection) veya SQL Server Authentication destekler.
    """
    driver = get_best_driver()
    
    conn_str = f"DRIVER={{{driver}}};SERVER={DB_SERVER};DATABASE={DB_DATABASE};"
    
    if USE_WINDOWS_AUTH:
        conn_str += "Trusted_Connection=yes;"
    else:
        conn_str += f"UID={DB_USERNAME};PWD={DB_PASSWORD};"
    
    # TrustServerCertificate sadece ODBC Driver 17/18 vb. modern sürücülerde desteklenir
    if "ODBC Driver" in driver:
        conn_str += f"TrustServerCertificate={DB_TRUST_CERT};"
        
    return conn_str


def get_connection() -> pyodbc.Connection:
    """
    Doğrudan bir pyodbc MSSQL veritabanı bağlantısı oluşturur ve döndürür.
    """
    conn_str = build_connection_string()
    return pyodbc.connect(conn_str)

@contextmanager
def get_db_connection():
    """
    Bağlantıyı güvenli bir şekilde yönetmek için context manager.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


if __name__ == "__main__":
    print("MSSQL Bağlantısı test ediliyor...")
    try:
        driver = get_best_driver()
        print(f"Kullanılan Sürücü: {driver}")
        print(f"Hedef Sunucu: {DB_SERVER}")
        print(f"Veritabanı: {DB_DATABASE}")
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT @@VERSION")
            db_version = cursor.fetchone()[0]
            print("\n[BAŞARILI] Veritabanı bağlantısı başarıyla kuruldu!")
            print(f"SQL Server Sürümü:\n{db_version.splitlines()[0]}")
    except Exception as e:
        print(f"\n[HATA] Veritabanına bağlanılamadı: {e}")


