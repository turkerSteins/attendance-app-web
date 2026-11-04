# Web Tabanlı Mesai Takip (Web Attendance) - Faz 1

Saha çalışanları için geliştirilen Web Tabanlı Mesai Takip projesinin veritabanı altyapısı ve proje iskeletidir.

## 🚀 Proje Yapısı

```text
web-attendance/
├── .env.example       # Örnek çevre değişkenleri ve veritabanı bağlantı konfigürasyonu
├── .gitignore          # Git tarafından takip edilmeyecek dosya kuralları
├── database.py         # MSSQL (pyodbc) dinamik bağlantı yöneticisi ve test fonksiyonu
├── init_db.py          # FieldAttendanceLogs tablosunu oluşturan kurulum scripti
├── requirements.txt    # Python bağımlılıkları (FastAPI, Uvicorn, pyodbc, python-dotenv)
└── README.md           # Proje dokümantasyonu
```

## 🛠️ Kurulum ve Kullanım

### 1. Bağımlılıkların Yüklenmesi
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. .env Yapılandırması
`.env.example` dosyasını kopyalayarak `.env` oluşturun ve MSSQL bilgilerinizi girin:
```env
SERVER=93.177.102.97
DATABASE=Personnel_Attendance_Control
USERNAME=MCS_Ext
PASSWORD=sifreniz
```

### 3. Veritabanı Bağlantı Testi ve Tablo Kurulumu
```powershell
# Bağlantı testi
python database.py

# Tablo kurulumu
python init_db.py
```

## 📊 Tablo Şeması: `FieldAttendanceLogs`

- **LogID** (`BIGINT IDENTITY PK`): Birincil anahtar
- **UserID** (`INT NOT NULL`): Saha çalışanı ID
- **ActionType** (`NVARCHAR(10) NOT NULL`): 'CHECK_IN' veya 'CHECK_OUT'
- **LocationDescription** (`NVARCHAR(255) NOT NULL`): Konum açıklaması
- **Latitude** (`FLOAT NULL`): Enlem bilgisi
- **Longitude** (`FLOAT NULL`): Boylam bilgisi
- **DeviceInfo** (`NVARCHAR(255) NULL`): Cihaz / Tarayıcı bilgisi
- **IPAddress** (`NVARCHAR(45) NULL`): İstemci IP adresi
- **LogDateTime** (`DATETIME2 DEFAULT GETDATE()`): İşlem zamanı
