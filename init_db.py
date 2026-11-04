import sys
import pyodbc
from database import get_db_connection
from auth import hash_password

# Bu uygulama veritabanı yapısının tek sahibidir. Her adım idempotenttir (tekrar çalıştırılması güvenlidir)
# ve ayrı bir batch olarak çalıştırılır: SQL Server, aynı batch içinde eklenen bir sütunun sonraki
# ifadelerde kullanılmasına izin vermez.

# ------------------------------------------------------------------
# 1) Tablolar (yeni kurulum)
# ------------------------------------------------------------------
CREATE_USERS_SQL = """
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Users')
BEGIN
    CREATE TABLE Users (
        UserID INT IDENTITY(1,1) PRIMARY KEY,
        EmployeeCode NVARCHAR(50) NOT NULL UNIQUE,
        FullName NVARCHAR(100) NOT NULL,
        CardUID NVARCHAR(50) NULL,  -- Benzersizlik aşağıdaki filtreli indeks ile sağlanır (birden fazla NULL'a izin verir)
        Password NVARCHAR(255) NOT NULL,
        Role NVARCHAR(20) NOT NULL CONSTRAINT CHK_UserRole CHECK (Role IN ('ADMIN', 'EMPLOYEE')),
        PasswordChangedAt DATETIME2 NULL,  -- UTC; bu andan önce açılmış oturumlar geçersizdir
        CreatedAt DATETIME2 DEFAULT GETDATE()
    );
    PRINT 'Users tablosu oluşturuldu.';
END
"""

CREATE_LOCATIONS_SQL = """
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Locations')
BEGIN
    CREATE TABLE Locations (
        LocationID INT IDENTITY(1,1) PRIMARY KEY,
        Code NVARCHAR(50) NOT NULL UNIQUE,
        DisplayName NVARCHAR(100) NOT NULL,
        IsActive BIT DEFAULT 1,
        CreatedAt DATETIME2 DEFAULT GETDATE()
    );
    PRINT 'Locations tablosu oluşturuldu.';
END
"""

CREATE_TERMINALS_SQL = """
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Terminals')
BEGIN
    CREATE TABLE Terminals (
        TerminalID INT IDENTITY(1,1) PRIMARY KEY,
        TerminalCode NVARCHAR(50) NOT NULL UNIQUE,
        LocationID INT NULL CONSTRAINT FK_Terminals_Locations REFERENCES Locations(LocationID),
        TerminalName NVARCHAR(100) NOT NULL,
        TerminalType NVARCHAR(50) NOT NULL DEFAULT 'KIOSK',
        TerminalKeyHash CHAR(64) NULL,
        IsActive BIT NOT NULL DEFAULT 1,
        LastSeenAt DATETIME2 NULL,
        LastSeenIP NVARCHAR(45) NULL,
        LastUnknownCardUID NVARCHAR(50) NULL,
        LastUnknownCardAt DATETIME2 NULL,
        CreatedAt DATETIME2 DEFAULT GETDATE()
    );
    PRINT 'Terminals tablosu oluşturuldu.';
END
"""

CREATE_LOGS_SQL = """
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'FieldAttendanceLogs')
BEGIN
    CREATE TABLE FieldAttendanceLogs (
        LogID BIGINT IDENTITY(1,1) PRIMARY KEY,
        UserID INT NOT NULL,
        ActionType NVARCHAR(10) NOT NULL CONSTRAINT CHK_ActionType CHECK (ActionType IN ('CHECK_IN', 'CHECK_OUT')),
        LocationDescription NVARCHAR(255) NOT NULL,
        Latitude FLOAT NULL,
        Longitude FLOAT NULL,
        DeviceInfo NVARCHAR(255) NULL,
        IPAddress NVARCHAR(45) NULL,
        ResolvedAddress NVARCHAR(500) NULL,
        TerminalID INT NULL CONSTRAINT FK_Logs_Terminals REFERENCES Terminals(TerminalID),  -- Kiosk kayıtlarında dolu
        -- [SERTIFIKA_MTLS_DEVRE_DISI]
        -- DeviceTrustStatus NVARCHAR(50) NULL,
        -- DeviceCertificateDN NVARCHAR(255) NULL,
        -- DeviceCertificateSerial NVARCHAR(64) NULL,
        -- IsTrustedDevice BIT NOT NULL CONSTRAINT DF_Attendance_IsTrustedDevice DEFAULT 0,
        LogDateTime DATETIME2 DEFAULT GETDATE()
    );
    PRINT 'FieldAttendanceLogs tablosu oluşturuldu.';
END
"""

# ------------------------------------------------------------------
# 2) Mevcut veritabanlarını güncel yapıya yükseltme
# ------------------------------------------------------------------
UPGRADE_USERS_COLUMNS_SQL = """
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('Users') AND name = 'PasswordChangedAt')
    ALTER TABLE Users ADD PasswordChangedAt DATETIME2 NULL;
"""

UPGRADE_LOGS_COLUMNS_SQL = """
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('FieldAttendanceLogs') AND name = 'ResolvedAddress')
    ALTER TABLE FieldAttendanceLogs ADD ResolvedAddress NVARCHAR(500) NULL;

IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('FieldAttendanceLogs') AND name = 'TerminalID')
    ALTER TABLE FieldAttendanceLogs ADD TerminalID INT NULL CONSTRAINT FK_Logs_Terminals REFERENCES Terminals(TerminalID);
"""

UPGRADE_TERMINALS_COLUMNS_SQL = """
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('Terminals') AND name = 'TerminalKeyHash')
    ALTER TABLE Terminals ADD TerminalKeyHash CHAR(64) NULL;
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('Terminals') AND name = 'LastSeenAt')
    ALTER TABLE Terminals ADD LastSeenAt DATETIME2 NULL;
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('Terminals') AND name = 'LastSeenIP')
    ALTER TABLE Terminals ADD LastSeenIP NVARCHAR(45) NULL;
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('Terminals') AND name = 'LastUnknownCardUID')
    ALTER TABLE Terminals ADD LastUnknownCardUID NVARCHAR(50) NULL;
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('Terminals') AND name = 'LastUnknownCardAt')
    ALTER TABLE Terminals ADD LastUnknownCardAt DATETIME2 NULL;
"""

# Eski şemada IsActive NULL olabiliyordu; kiosk doğrulaması IsActive = 1 arar
UPGRADE_TERMINALS_ISACTIVE_SQL = """
UPDATE Terminals SET IsActive = 1 WHERE IsActive IS NULL;
"""

# Eski şemadaki "CardUID UNIQUE" kısıtı SQL Server'da yalnızca TEK bir NULL'a izin verir;
# bu yüzden kartsız ikinci kullanıcı eklenemiyordu. Kısıt kaldırılıp filtreli benzersiz indeks ile değiştirilir.
UPGRADE_CARDUID_UNIQUE_SQL = """
DECLARE @uq SYSNAME = (
    SELECT TOP 1 kc.name
    FROM sys.key_constraints kc
    JOIN sys.index_columns ic ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
    JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    WHERE kc.parent_object_id = OBJECT_ID('Users') AND kc.type = 'UQ' AND c.name = 'CardUID'
);
IF @uq IS NOT NULL
BEGIN
    EXEC('ALTER TABLE Users DROP CONSTRAINT ' + @uq);
    PRINT 'Users.CardUID üzerindeki eski UNIQUE kısıtı kaldırıldı.';
END
"""

# Kart UID'leri okuyucudan bağımsız tek biçimde saklanır: ayraçsız, büyük harf (bkz. main.normalize_card_uid)
NORMALIZE_CARDUIDS_SQL = """
UPDATE Users
SET CardUID = NULLIF(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(CardUID)), ' ', ''), ':', ''), '-', ''), '.', '')), '')
WHERE CardUID IS NOT NULL
  AND CardUID <> ISNULL(NULLIF(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(CardUID)), ' ', ''), ':', ''), '-', ''), '.', '')), ''), '')
  COLLATE Latin1_General_BIN2;
"""

CREATE_INDEXES_SQL = """
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'UX_Users_CardUID' AND object_id = OBJECT_ID('Users'))
    CREATE UNIQUE INDEX UX_Users_CardUID ON Users(CardUID) WHERE CardUID IS NOT NULL;

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'UX_Terminals_KeyHash' AND object_id = OBJECT_ID('Terminals'))
    CREATE UNIQUE INDEX UX_Terminals_KeyHash ON Terminals(TerminalKeyHash) WHERE TerminalKeyHash IS NOT NULL;

-- Çalışanın son hareketini bulan sorgular (durum, kiosk okutma) için
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Logs_User_Time' AND object_id = OBJECT_ID('FieldAttendanceLogs'))
    CREATE INDEX IX_Logs_User_Time ON FieldAttendanceLogs(UserID, LogDateTime DESC, LogID DESC);
"""

# ------------------------------------------------------------------
# 3) Varsayılan veriler
# ------------------------------------------------------------------
SEED_ADMIN_SQL = """
IF NOT EXISTS (SELECT 1 FROM Users WHERE Role = 'ADMIN' OR EmployeeCode = 'admin')
BEGIN
    INSERT INTO Users (EmployeeCode, FullName, CardUID, Password, Role, CreatedAt)
    VALUES ('admin', N'Sistem Yöneticisi', NULL, ?, 'ADMIN', GETDATE());
    PRINT 'Varsayılan Admin kullanıcısı (admin / admin123) oluşturuldu.';
END
"""

SEED_LOCATIONS_SQL = """
IF NOT EXISTS (SELECT 1 FROM Locations WHERE Code = 'OFIS')
    INSERT INTO Locations (Code, DisplayName, IsActive) VALUES ('OFIS', N'Merkez Ofis', 1);

IF NOT EXISTS (SELECT 1 FROM Locations WHERE Code = 'ATOLYE')
    INSERT INTO Locations (Code, DisplayName, IsActive) VALUES ('ATOLYE', N'Atölye', 1);

IF NOT EXISTS (SELECT 1 FROM Locations WHERE Code = 'SAHA')
    INSERT INTO Locations (Code, DisplayName, IsActive) VALUES ('SAHA', N'Saha / Şantiye', 1);
"""

SCHEMA_STEPS = [
    CREATE_USERS_SQL,
    CREATE_LOCATIONS_SQL,
    CREATE_TERMINALS_SQL,
    CREATE_LOGS_SQL,
    UPGRADE_USERS_COLUMNS_SQL,
    UPGRADE_LOGS_COLUMNS_SQL,
    UPGRADE_TERMINALS_COLUMNS_SQL,
    UPGRADE_TERMINALS_ISACTIVE_SQL,
    UPGRADE_CARDUID_UNIQUE_SQL,
    NORMALIZE_CARDUIDS_SQL,
    CREATE_INDEXES_SQL,
]


def init_db():
    print("MSSQL Veritabanına bağlanılıyor ve tablo kurulumu başlatılıyor...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            for step in SCHEMA_STEPS:
                cursor.execute(step)
                conn.commit()
            cursor.execute(SEED_ADMIN_SQL, (hash_password("admin123"),))
            cursor.execute(SEED_LOCATIONS_SQL)
            conn.commit()
            print("Tablo kurulumu ve varsayılan veri işlemleri başarıyla tamamlandı.")
    except pyodbc.Error as ex:
        sqlstate = ex.args[1] if len(ex.args) > 1 else str(ex)
        print(f"HATA: MSSQL Veritabanı bağlantısı veya tablo oluşturma başarısız oldu:\n{sqlstate}")
        sys.exit(1)
    except Exception as e:
        print(f"Beklenmeyen Hata: {e}")
        sys.exit(1)

if __name__ == "__main__":
    init_db()
