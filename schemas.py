from enum import Enum
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal, Union, List
from datetime import datetime

# Tüm şifre belirleme yolları (kullanıcı oluşturma, admin şifre belirleme, kendi şifresini değiştirme) için ortak kural
PASSWORD_MIN_LENGTH = 8


def normalize_new_password(value: str) -> str:
    """
    Giriş formu şifrenin başındaki/sonundaki boşlukları kırptığı için şifre kırpılmış haliyle saklanır;
    uzunluk kontrolü de kırpılmış değer üzerinden yapılır.
    """
    value = value.strip()
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Şifre en az {PASSWORD_MIN_LENGTH} karakter olmalıdır.")
    return value


class LocationEnum(str, Enum):
    """
    Sistem sabit konum kodları (Enum)
    """
    OFIS = "OFIS"
    ATOLYE = "ATOLYE"
    SAHA = "SAHA"

class LocationResponse(BaseModel):
    """
    Konum verisi yanıt şeması.
    """
    LocationID: int
    Code: str
    DisplayName: str
    IsActive: bool = True

    class Config:
        from_attributes = True

class AttendanceLogCreate(BaseModel):
    """
    Saha çalışanından gelen giriş/çıkış isteği için doğrulama şeması.
    """
    UserID: Optional[Union[int, str]] = Field(None, description="Kullanılmaz: kullanıcı kimliği oturum token'ından alınır (geriye dönük uyumluluk için tutulur)", example="101")
    ActionType: Optional[Literal["CHECK_IN", "CHECK_OUT"]] = Field(
        None, 
        description="Mesai hareket türü: CHECK_IN veya CHECK_OUT",
        example="CHECK_IN"
    )
    LocationDescription: Optional[str] = Field(
        None, 
        max_length=255, 
        description="Konum metin açıklaması (Boş bırakılırsa aktif SAHA DisplayName kullanılır)",
        example="Saha / Şantiye"
    )
    Latitude: Optional[float] = Field(None, description="GPS Enlem bilgisi", example=41.0082)
    Longitude: Optional[float] = Field(None, description="GPS Boylam bilgisi", example=28.9784)
    DeviceInfo: Optional[str] = Field(None, max_length=255, description="İstemci cihaz veya tarayıcı bilgisi")
    ResolvedAddress: Optional[str] = Field(None, max_length=500, description="Ters coğrafi kodlama ile çözümlenen açık adres (Sokak, İlçe, Şehir)")

class AttendanceLogResponse(BaseModel):
    """
    Veritabanından dönen mesai kaydı yanıt şeması.
    """
    LogID: int
    UserID: int
    ActionType: str
    LocationDescription: str
    Latitude: Optional[float] = None
    Longitude: Optional[float] = None
    DeviceInfo: Optional[str] = None
    IPAddress: Optional[str] = None
    ResolvedAddress: Optional[str] = None
    # [SERTIFIKA_MTLS_DEVRE_DISI]
    # DeviceTrustStatus: Optional[str] = None
    # DeviceCertificateDN: Optional[str] = None
    # DeviceCertificateSerial: Optional[str] = None
    # IsTrustedDevice: Optional[bool] = False
    LogDateTime: datetime

    class Config:
        from_attributes = True

class AttendanceStatusResponse(BaseModel):
    """
    Çalışanın anlık durumunu gösteren yanıt şeması.
    """
    UserID: int
    FullName: Optional[str] = Field(None, description="Çalışanın Adı Soyadı")
    is_checked_in: bool = Field(..., description="Şu an giriş yapmış/mesaide mi?")
    last_action: Optional[str] = Field(None, description="Son hareket türü (CHECK_IN veya CHECK_OUT)")
    last_location: Optional[str] = Field(None, description="Son konum açıklaması")
    last_log_time: Optional[datetime] = Field(None, description="Son işlem tarihi ve saati")

# ==========================================
# ADMIN & KULLANICI ŞEMALARI
# ==========================================

class UserCreate(BaseModel):
    """
    Yeni kullanıcı/çalışan oluşturma isteği için doğrulama şeması.
    """
    FullName: str = Field(..., min_length=2, max_length=100, description="Çalışanın Adı Soyadı", example="Ahmet Yılmaz")
    EmployeeCode: str = Field(..., min_length=1, max_length=50, description="Çalışan Kodu veya ID'si", example="EMP-101")
    CardUID: Optional[str] = Field(None, max_length=50, description="RFID Kart UID'si", example="A1B2C3D4")
    Password: str = Field(..., max_length=255, description=f"Giriş Şifresi (en az {PASSWORD_MIN_LENGTH} karakter)", example="Guclu.Sifre1")
    Role: Literal["ADMIN", "EMPLOYEE"] = Field("EMPLOYEE", description="Kullanıcı Rolü: ADMIN veya EMPLOYEE", example="EMPLOYEE")

    _check_password = field_validator("Password")(normalize_new_password)

class UserResponse(BaseModel):
    """
    Kullanıcı yanıt şeması.
    """
    UserID: int
    EmployeeCode: str
    FullName: str
    CardUID: Optional[str] = None
    Role: str
    CreatedAt: Optional[datetime] = None

    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    """
    Giriş isteği şeması.
    """
    EmployeeCode: str = Field(..., description="Çalışan Kodu, Ad Soyad veya Yönetici Kullanıcı Adı")
    Password: str = Field(..., description="Kullanıcı şifresi")

class PasswordSetRequest(BaseModel):
    """Admin'in bir kullanıcıya şifre belirlemesi."""
    NewPassword: str = Field(..., max_length=255, description=f"Yeni şifre (en az {PASSWORD_MIN_LENGTH} karakter)")

    _check_password = field_validator("NewPassword")(normalize_new_password)

class PasswordChangeRequest(BaseModel):
    """Kullanıcının kendi şifresini değiştirmesi; mevcut şifre doğrulanır."""
    CurrentPassword: str = Field(..., max_length=255, description="Mevcut şifre")
    NewPassword: str = Field(..., max_length=255, description=f"Yeni şifre (en az {PASSWORD_MIN_LENGTH} karakter)")

    _check_password = field_validator("NewPassword")(normalize_new_password)

class PasswordChangeResponse(BaseModel):
    """Şifre değişince eski oturumlar geçersiz olur; değiştiren kullanıcı oturumunu yeni token ile sürdürür."""
    message: str
    token: str

class MessageResponse(BaseModel):
    success: bool
    message: str

class LoginResponse(BaseModel):
    """
    Giriş yanıtı şeması.
    """
    success: bool
    message: str
    token: Optional[str] = Field(None, description="Sonraki isteklerde 'Authorization: Bearer <token>' olarak gönderilecek oturum anahtarı")
    user: Optional[UserResponse] = None

class AttendanceReportLog(BaseModel):
    """
    Admin paneli için detaylı mesai rapor kaydı.
    """
    LogID: int
    UserID: int
    EmployeeCode: Optional[str] = None
    EmployeeName: Optional[str] = None
    ActionType: Optional[str] = "CHECK_IN"
    LocationDescription: Optional[str] = ""
    Latitude: Optional[float] = None
    Longitude: Optional[float] = None
    DeviceInfo: Optional[str] = None
    IPAddress: Optional[str] = None
    ResolvedAddress: Optional[str] = None
    # [SERTIFIKA_MTLS_DEVRE_DISI]
    # DeviceTrustStatus: Optional[str] = None
    # DeviceCertificateDN: Optional[str] = None
    # DeviceCertificateSerial: Optional[str] = None
    # IsTrustedDevice: Optional[bool] = False
    LogDateTime: datetime

    class Config:
        from_attributes = True

class EmployeeSummary(BaseModel):
    """
    Çalışana ait özeti gösteren şema (Toplam mesai, tahmini çalışma saati vb.)
    """
    UserID: int
    EmployeeCode: str
    FullName: str
    total_records: int = Field(0, description="Seçilen dönemdeki toplam hareket/kayıt sayısı")
    total_work_hours: float = Field(0.0, description="Eşleşen giriş/çıkışlardan hesaplanan tahmini toplam çalışma saati")

class EmployeeAttendanceReportResponse(BaseModel):
    """
    Çalışana özel mesai raporu yanıt şeması.
    """
    employee: Optional[EmployeeSummary] = None
    records: List[AttendanceReportLog] = []



# ==========================================
# KİOSK TERMİNAL ŞEMALARI
# ==========================================

class KioskPunchRequest(BaseModel):
    """
    Kiosk kart okutma isteği. Terminal kimliği Authorization başlığından, saat ve konum sunucudan alınır.
    """
    CardUID: str = Field(..., min_length=1, max_length=100, description="Okuyucudan gelen kart UID'si (ayraçlar ve harf büyüklüğü önemsizdir)", example="04:A1:B2:C3")

class KioskPunchResponse(BaseModel):
    """
    Kiosk ekranının doğrudan gösterebileceği okutma sonucu. Ekran 'result' alanına göre davranır;
    'message' hazır Türkçe metindir.
    """
    result: Literal["CHECK_IN", "CHECK_OUT", "TOO_SOON", "UNKNOWN_CARD"] = Field(
        ...,
        description="CHECK_IN: giriş kaydedildi, CHECK_OUT: çıkış kaydedildi, TOO_SOON: son hareketten çok kısa süre geçti (kayıt yapılmadı), UNKNOWN_CARD: kart hiçbir çalışana tanımlı değil"
    )
    message: str = Field(..., description="Ekranda gösterilecek hazır mesaj")
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    action_time: Optional[datetime] = Field(None, description="Kaydedilen hareketin zamanı; TOO_SOON için son hareketin zamanı")
    last_action: Optional[Literal["CHECK_IN", "CHECK_OUT"]] = Field(None, description="TOO_SOON için zaten kaydedilmiş olan son hareket")
    retry_after_seconds: Optional[int] = Field(None, description="TOO_SOON için tekrar okutmadan önce beklenmesi gereken süre")
    warning: Optional[Literal["MISSING_CHECKOUT"]] = Field(None, description="MISSING_CHECKOUT: önceki girişin çıkışı yapılmamıştı; yeni giriş açıldı")
    location: Optional[str] = None

class KioskPingResponse(BaseModel):
    """Kiosk açılışta ve periyodik olarak terminal anahtarını ve bağlantıyı doğrular."""
    terminal_code: str
    terminal_name: str
    location: Optional[str] = None
    server_time: datetime

class TerminalCreate(BaseModel):
    TerminalCode: str = Field(..., min_length=1, max_length=50, description="Benzersiz terminal kodu", example="KIOSK-ATOLYE-1")
    TerminalName: str = Field(..., min_length=1, max_length=100, description="Terminal adı", example="Atölye Giriş Kapısı")
    LocationID: Optional[int] = Field(None, description="Okutmaların kaydedileceği konum")

class TerminalUpdate(BaseModel):
    IsActive: bool = Field(..., description="False: terminal devre dışı, anahtarı kabul edilmez")

class TerminalResponse(BaseModel):
    TerminalID: int
    TerminalCode: str
    TerminalName: str
    LocationID: Optional[int] = None
    LocationName: Optional[str] = None
    IsActive: bool
    HasKey: bool = Field(..., description="Terminale anahtar üretilmiş mi")
    LastSeenAt: Optional[datetime] = None
    LastSeenIP: Optional[str] = None
    LastUnknownCardUID: Optional[str] = Field(None, description="Bu terminalde en son okutulan tanımsız kart (yeni kart tanımlarken UID'yi öğrenmek için)")
    LastUnknownCardAt: Optional[datetime] = None
    CreatedAt: Optional[datetime] = None

class TerminalKeyResponse(BaseModel):
    """Anahtar yalnızca oluşturma/yenileme yanıtında bir kez döner; sonra tekrar gösterilemez."""
    terminal: TerminalResponse
    TerminalKey: str


# ==========================================
# PERSONEL TOPLU ÇALIŞMA SÜRESİ VE EXCEL RAPOR ŞEMALARI
# ==========================================

class PersonnelWorkHoursItem(BaseModel):
    UserID: int
    EmployeeCode: Optional[str] = ""
    FullName: Optional[str] = ""
    Role: Optional[str] = "EMPLOYEE"
    TotalCheckIns: int = 0
    TotalCheckOuts: int = 0
    DaysWorked: int = 0
    TotalWorkSeconds: float = 0.0
    TotalWorkHours: float = 0.0
    FormattedWorkDuration: str = "0 sa 0 dk"
    FirstPunch: Optional[datetime] = None
    LastPunch: Optional[datetime] = None
    IsCurrentlyActive: bool = False

    class Config:
        from_attributes = True


class PersonnelWorkHoursReportResponse(BaseModel):
    filter_range: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    total_personnel_count: int = 0
    total_active_personnel: int = 0
    total_hours_sum: float = 0.0
    average_hours: float = 0.0
    items: List[PersonnelWorkHoursItem] = []

    class Config:
        from_attributes = True


# ==========================================
# CANLI SAHA HARİTASI (LIVE MAP) ŞEMALARI
# ==========================================

class LiveMapItem(BaseModel):
    LogID: int
    UserID: int
    EmployeeCode: Optional[str] = ""
    FullName: Optional[str] = ""
    Role: Optional[str] = "EMPLOYEE"
    ActionType: str
    LocationDescription: Optional[str] = ""
    Latitude: Optional[float] = None
    Longitude: Optional[float] = None
    DeviceInfo: Optional[str] = None
    IPAddress: Optional[str] = None
    ResolvedAddress: Optional[str] = None
    LogDateTime: datetime
    IsCurrentlyActive: bool = False
    MinutesAgo: int = 0
    TimeFormatted: str = ""
    HasCoordinates: bool = False

    class Config:
        from_attributes = True


class LiveMapResponse(BaseModel):
    filter_mode: str
    server_time: datetime
    total_personnel_reported: int = 0
    with_coordinates_count: int = 0
    without_coordinates_count: int = 0
    currently_active_count: int = 0
    items: List[LiveMapItem] = []

    class Config:
        from_attributes = True


