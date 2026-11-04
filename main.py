import os
from fastapi import FastAPI, HTTPException, Request, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Optional, Union
import pyodbc

from database import get_db_connection
from auth import (
    hash_password, verify_password, is_password_hashed, create_access_token, require_admin, require_user,
    require_terminal, generate_terminal_key, hash_terminal_key, set_user_password
)
# [SERTIFIKA_MTLS_DEVRE_DISI]
# from device_trust import get_device_trust_info, DeviceTrustInfo
from schemas import (
    AttendanceLogCreate,
    AttendanceLogResponse,
    AttendanceStatusResponse,
    UserCreate,
    UserResponse,
    LoginRequest,
    LoginResponse,
    AttendanceReportLog,
    EmployeeSummary,
    EmployeeAttendanceReportResponse,
    LocationEnum,
    LocationResponse,
    KioskPunchRequest,
    KioskPunchResponse,
    KioskPingResponse,
    TerminalCreate,
    TerminalUpdate,
    TerminalResponse,
    TerminalKeyResponse,
    PasswordSetRequest,
    PasswordChangeRequest,
    PasswordChangeResponse,
    MessageResponse
)

app = FastAPI(
    title="Web Attendance API",
    description="Saha Çalışanları Web Tabanlı Mesai Takip (Web Attendance) Servisi",
    version="1.0.0"
)

# CORS Middleware (Tarayıcıdan erişim izinleri için)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Geliştirme aşamasında tüm originlere izin veriyoruz
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static dosyaları (HTML/CSS/JS) sunmak için mount etme
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

def get_client_ip(request: Request) -> str:
    """İstemci IP adresini HTTP başlıklarından veya doğrudan soketten yakalar."""
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def normalize_card_uid(raw: Optional[str]) -> Optional[str]:
    """
    Kart UID'sini okuyucudan bağımsız tek biçime getirir: boşluk ve ayraçlar (: - .) kaldırılır, büyük harfe çevrilir.
    Örn: '04:a1:b2:c3' ve '04 A1 B2 C3' -> '04A1B2C3'. init_db.NORMALIZE_CARDUIDS_SQL ile aynı kural.
    """
    if raw is None:
        return None
    cleaned = raw.strip()
    for sep in (" ", ":", "-", "."):
        cleaned = cleaned.replace(sep, "")
    return cleaned.upper() or None


def get_resolved_user_id(user_param: Union[int, str]) -> tuple[int, str]:
    """
    Parametre olarak gelen UserID veya EmployeeCode değerini Users tablosundan çözümler.
    Sayısal parametrelerde öncelikle exact UserID, sonrasında EmployeeCode eşleştirmesi yapar.
    (int_user_id, full_name) çiftini döndürür.
    """
    str_val = str(user_param).strip()
    is_num = str_val.isdigit()

    if is_num:
        user_query = """
            SELECT TOP 1 UserID, FullName
            FROM Users
            WHERE UserID = ? OR EmployeeCode = ?
            ORDER BY CASE WHEN UserID = ? THEN 0 ELSE 1 END;
        """
        params = (int(str_val), str_val, int(str_val))
    else:
        user_query = """
            SELECT UserID, FullName
            FROM Users
            WHERE EmployeeCode = ? OR LOWER(FullName) = LOWER(?);
        """
        params = (str_val, str_val)

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(user_query, params)
            row = cursor.fetchone()
            if row:
                return (row.UserID, row.FullName)
    except Exception:
        pass
    
    fallback_id = int(str_val) if is_num else 0
    fallback_name = f"Çalışan #{str_val}" if is_num else str_val
    return (fallback_id, fallback_name)


def ensure_can_access_user(current_user: dict, target_user_id: int) -> None:
    """Çalışanlar yalnızca kendi kayıtlarına erişebilir; ADMIN tüm çalışanları görebilir."""
    if current_user["role"] != "ADMIN" and current_user["uid"] != target_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Başka bir çalışanın kayıtlarına erişim yetkiniz yok.")


def get_location_display_name(code: str = LocationEnum.SAHA.value) -> str:
    """
    Locations tablosundan belirtilen Code (Örn: 'SAHA') için aktif DisplayName getirir.
    Veritabanına ulaşılamazsa veya kayıt yoksa varsayılan fallback değerini döner.
    """
    query_sql = "SELECT TOP 1 DisplayName FROM Locations WHERE Code = ? AND IsActive = 1;"
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query_sql, (code.strip().upper(),))
            row = cursor.fetchone()
            if row and row.DisplayName:
                return row.DisplayName
    except Exception:
        pass
    
    fallback_map = {
        LocationEnum.OFIS.value: "Merkez Ofis",
        LocationEnum.ATOLYE.value: "Atölye",
        LocationEnum.SAHA.value: "Saha / Şantiye"
    }
    return fallback_map.get(code.upper(), "Saha / Şantiye")


@app.get("/", include_in_schema=False)
def read_index():
    """
    Saha çalışanları için web arayüzünü (index.html) sunar.
    """
    return FileResponse("static/index.html")


@app.get("/api/v1/health", tags=["Health Check"])
def health_check():
    """
    API Sağlık Kontrolü (Health Check) Endpoint'i
    """
    return {
        "status": "success",
        "message": "Web Attendance API servisi aktif ve çalışıyor.",
        "docs": "/docs"
    }


@app.get("/api/v1/client-info", tags=["Client Info"])
def get_client_info(request: Request):
    """
    İstemcinin IP adresini ve User-Agent bilgisini döner.
    """
    return {
        "ip": get_client_ip(request),
        "user_agent": request.headers.get("user-agent", "")
    }


@app.post(
    "/api/v1/attendance/check-in",
    response_model=AttendanceLogResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Attendance Operations"]
)
def check_in(
    payload: AttendanceLogCreate,
    request: Request,
    current_user: dict = Depends(require_user),
    # [SERTIFIKA_MTLS_DEVRE_DISI]
    # device_trust: DeviceTrustInfo = Depends(get_device_trust_info)
):
    """
    Saha çalışanı Giriş (CHECK_IN) kaydı oluşturur.
    """
    ip_address = get_client_ip(request)
    action_type = "CHECK_IN"
    # Kullanıcı kimliği istek gövdesinden değil, oturum token'ından alınır
    actual_user_id = current_user["uid"]
    loc_desc = payload.LocationDescription.strip() if payload.LocationDescription and payload.LocationDescription.strip() else get_location_display_name(LocationEnum.SAHA.value)

    check_last_sql = """
        SELECT TOP 1 LogID, UserID, ActionType, LocationDescription, Latitude, Longitude, DeviceInfo, IPAddress, ResolvedAddress,
               -- [SERTIFIKA_MTLS_DEVRE_DISI] DeviceTrustStatus, DeviceCertificateDN, DeviceCertificateSerial, IsTrustedDevice,
               LogDateTime,
               DATEDIFF(SECOND, LogDateTime, GETDATE()) AS SecDiff
        FROM FieldAttendanceLogs
        WHERE UserID = ?
        ORDER BY LogDateTime DESC, LogID DESC;
    """

    insert_sql = """
        INSERT INTO FieldAttendanceLogs (
            UserID, ActionType, LocationDescription, Latitude, Longitude, DeviceInfo, IPAddress, ResolvedAddress,
            -- [SERTIFIKA_MTLS_DEVRE_DISI] DeviceTrustStatus, DeviceCertificateDN, DeviceCertificateSerial, IsTrustedDevice,
            LogDateTime
        )
        OUTPUT INSERTED.LogID, INSERTED.UserID, INSERTED.ActionType, INSERTED.LocationDescription, 
               INSERTED.Latitude, INSERTED.Longitude, INSERTED.DeviceInfo, INSERTED.IPAddress, INSERTED.ResolvedAddress,
               -- [SERTIFIKA_MTLS_DEVRE_DISI] INSERTED.DeviceTrustStatus, INSERTED.DeviceCertificateDN, INSERTED.DeviceCertificateSerial, INSERTED.IsTrustedDevice,
               INSERTED.LogDateTime
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, GETDATE());
    """
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(check_last_sql, (actual_user_id,))
            last_log = cursor.fetchone()
            if last_log and last_log.ActionType == "CHECK_IN":
                sec_diff = getattr(last_log, "SecDiff", None)
                if sec_diff is not None and abs(sec_diff) <= 10:
                    # Idempotency / Rate-limiting: return existing log record without inserting duplicate
                    return AttendanceLogResponse(
                        LogID=last_log.LogID,
                        UserID=last_log.UserID,
                        ActionType=last_log.ActionType,
                        LocationDescription=last_log.LocationDescription,
                        Latitude=last_log.Latitude,
                        Longitude=last_log.Longitude,
                        DeviceInfo=last_log.DeviceInfo,
                        IPAddress=last_log.IPAddress,
                        ResolvedAddress=last_log.ResolvedAddress,
                        # [SERTIFIKA_MTLS_DEVRE_DISI]
                        # DeviceTrustStatus=getattr(last_log, "DeviceTrustStatus", None),
                        # DeviceCertificateDN=getattr(last_log, "DeviceCertificateDN", None),
                        # DeviceCertificateSerial=getattr(last_log, "DeviceCertificateSerial", None),
                        # IsTrustedDevice=bool(getattr(last_log, "IsTrustedDevice", False)),
                        LogDateTime=last_log.LogDateTime
                    )
                else:
                    raise HTTPException(
                        status_code=400,
                        detail="Zaten aktif bir işe başlama (CHECK_IN) kaydınız bulunmaktadır. Tekrar giriş yapamazsınız."
                    )

            cursor.execute(
                insert_sql,
                (
                    actual_user_id,
                    action_type,
                    loc_desc,
                    payload.Latitude,
                    payload.Longitude,
                    payload.DeviceInfo,
                    ip_address,
                    payload.ResolvedAddress,
                    # [SERTIFIKA_MTLS_DEVRE_DISI]
                    # device_trust.device_trust_status,
                    # device_trust.certificate_dn,
                    # device_trust.certificate_serial,
                    # 1 if device_trust.is_trusted_device else 0
                )
            )
            row = cursor.fetchone()
            conn.commit()
            
            if not row:
                raise HTTPException(status_code=500, detail="Kayıt ekleme işlemi gerçekleşti ancak dönen veri alınamadı.")

            return AttendanceLogResponse(
                LogID=row.LogID,
                UserID=row.UserID,
                ActionType=row.ActionType,
                LocationDescription=row.LocationDescription,
                Latitude=row.Latitude,
                Longitude=row.Longitude,
                DeviceInfo=row.DeviceInfo,
                IPAddress=row.IPAddress,
                ResolvedAddress=row.ResolvedAddress,
                # [SERTIFIKA_MTLS_DEVRE_DISI]
                # DeviceTrustStatus=getattr(row, "DeviceTrustStatus", None),
                # DeviceCertificateDN=getattr(row, "DeviceCertificateDN", None),
                # DeviceCertificateSerial=getattr(row, "DeviceCertificateSerial", None),
                # IsTrustedDevice=bool(getattr(row, "IsTrustedDevice", False)),
                LogDateTime=row.LogDateTime
            )
    except HTTPException:
        raise
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")


@app.post(
    "/api/v1/attendance/check-out",
    response_model=AttendanceLogResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Attendance Operations"]
)
def check_out(
    payload: AttendanceLogCreate,
    request: Request,
    current_user: dict = Depends(require_user),
    # [SERTIFIKA_MTLS_DEVRE_DISI]
    # device_trust: DeviceTrustInfo = Depends(get_device_trust_info)
):
    """
    Saha çalışanı Çıkış (CHECK_OUT) kaydı oluşturur.
    """
    ip_address = get_client_ip(request)
    action_type = "CHECK_OUT"
    # Kullanıcı kimliği istek gövdesinden değil, oturum token'ından alınır
    actual_user_id = current_user["uid"]
    loc_desc = payload.LocationDescription.strip() if payload.LocationDescription and payload.LocationDescription.strip() else get_location_display_name(LocationEnum.SAHA.value)

    check_last_sql = """
        SELECT TOP 1 LogID, UserID, ActionType, LocationDescription, Latitude, Longitude, DeviceInfo, IPAddress, ResolvedAddress,
               -- [SERTIFIKA_MTLS_DEVRE_DISI] DeviceTrustStatus, DeviceCertificateDN, DeviceCertificateSerial, IsTrustedDevice,
               LogDateTime,
               DATEDIFF(SECOND, LogDateTime, GETDATE()) AS SecDiff
        FROM FieldAttendanceLogs
        WHERE UserID = ?
        ORDER BY LogDateTime DESC, LogID DESC;
    """

    insert_sql = """
        INSERT INTO FieldAttendanceLogs (
            UserID, ActionType, LocationDescription, Latitude, Longitude, DeviceInfo, IPAddress, ResolvedAddress,
            -- [SERTIFIKA_MTLS_DEVRE_DISI] DeviceTrustStatus, DeviceCertificateDN, DeviceCertificateSerial, IsTrustedDevice,
            LogDateTime
        )
        OUTPUT INSERTED.LogID, INSERTED.UserID, INSERTED.ActionType, INSERTED.LocationDescription, 
               INSERTED.Latitude, INSERTED.Longitude, INSERTED.DeviceInfo, INSERTED.IPAddress, INSERTED.ResolvedAddress,
               -- [SERTIFIKA_MTLS_DEVRE_DISI] INSERTED.DeviceTrustStatus, INSERTED.DeviceCertificateDN, INSERTED.DeviceCertificateSerial, INSERTED.IsTrustedDevice,
               INSERTED.LogDateTime
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, GETDATE());
    """
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(check_last_sql, (actual_user_id,))
            last_log = cursor.fetchone()

            if last_log and last_log.ActionType == "CHECK_OUT":
                sec_diff = getattr(last_log, "SecDiff", None)
                if sec_diff is not None and abs(sec_diff) <= 10:
                    # Idempotency / Rate-limiting: return existing log record without inserting duplicate
                    return AttendanceLogResponse(
                        LogID=last_log.LogID,
                        UserID=last_log.UserID,
                        ActionType=last_log.ActionType,
                        LocationDescription=last_log.LocationDescription,
                        Latitude=last_log.Latitude,
                        Longitude=last_log.Longitude,
                        DeviceInfo=last_log.DeviceInfo,
                        IPAddress=last_log.IPAddress,
                        ResolvedAddress=last_log.ResolvedAddress,
                        # [SERTIFIKA_MTLS_DEVRE_DISI]
                        # DeviceTrustStatus=getattr(last_log, "DeviceTrustStatus", None),
                        # DeviceCertificateDN=getattr(last_log, "DeviceCertificateDN", None),
                        # DeviceCertificateSerial=getattr(last_log, "DeviceCertificateSerial", None),
                        # IsTrustedDevice=bool(getattr(last_log, "IsTrustedDevice", False)),
                        LogDateTime=last_log.LogDateTime
                    )
                else:
                    raise HTTPException(
                        status_code=400,
                        detail="Aktif bir mesai giriş (CHECK_IN) kaydınız bulunmamaktadır. Önce işe başla yapmalısınız."
                    )

            if not last_log or last_log.ActionType != "CHECK_IN":
                raise HTTPException(
                    status_code=400,
                    detail="Aktif bir mesai giriş (CHECK_IN) kaydınız bulunmamaktadır. Önce işe başla yapmalısınız."
                )

            cursor.execute(
                insert_sql,
                (
                    actual_user_id,
                    action_type,
                    loc_desc,
                    payload.Latitude,
                    payload.Longitude,
                    payload.DeviceInfo,
                    ip_address,
                    payload.ResolvedAddress,
                    # [SERTIFIKA_MTLS_DEVRE_DISI]
                    # device_trust.device_trust_status,
                    # device_trust.certificate_dn,
                    # device_trust.certificate_serial,
                    # 1 if device_trust.is_trusted_device else 0
                )
            )
            row = cursor.fetchone()
            conn.commit()

            if not row:
                raise HTTPException(status_code=500, detail="Kayıt ekleme işlemi gerçekleşti ancak dönen veri alınamadı.")

            return AttendanceLogResponse(
                LogID=row.LogID,
                UserID=row.UserID,
                ActionType=row.ActionType,
                LocationDescription=row.LocationDescription,
                Latitude=row.Latitude,
                Longitude=row.Longitude,
                DeviceInfo=row.DeviceInfo,
                IPAddress=row.IPAddress,
                ResolvedAddress=row.ResolvedAddress,
                # [SERTIFIKA_MTLS_DEVRE_DISI]
                # DeviceTrustStatus=getattr(row, "DeviceTrustStatus", None),
                # DeviceCertificateDN=getattr(row, "DeviceCertificateDN", None),
                # DeviceCertificateSerial=getattr(row, "DeviceCertificateSerial", None),
                # IsTrustedDevice=bool(getattr(row, "IsTrustedDevice", False)),
                LogDateTime=row.LogDateTime
            )
    except HTTPException:
        raise
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")


@app.get(
    "/api/v1/attendance/status/{user_id_param}",
    response_model=AttendanceStatusResponse,
    tags=["Attendance Query"]
)
def get_attendance_status(user_id_param: str, current_user: dict = Depends(require_user)):
    """
    Belirtilen çalışanın anlık mesai durumunu ve ad soyad bilgisini getirir.
    """
    actual_user_id, full_name = get_resolved_user_id(user_id_param)
    ensure_can_access_user(current_user, actual_user_id)

    log_query = """
        SELECT TOP 1 ActionType, LocationDescription, LogDateTime
        FROM FieldAttendanceLogs
        WHERE UserID = ?
        ORDER BY LogDateTime DESC, LogID DESC;
    """

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(log_query, (actual_user_id,))
            log_row = cursor.fetchone()

            if not log_row:
                return AttendanceStatusResponse(
                    UserID=actual_user_id,
                    FullName=full_name,
                    is_checked_in=False,
                    last_action=None,
                    last_location=None,
                    last_log_time=None
                )

            is_in = (log_row.ActionType == "CHECK_IN")
            return AttendanceStatusResponse(
                UserID=actual_user_id,
                FullName=full_name,
                is_checked_in=is_in,
                last_action=log_row.ActionType,
                last_location=log_row.LocationDescription,
                last_log_time=log_row.LogDateTime
            )
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")


@app.get(
    "/api/v1/attendance/history/{user_id_param}",
    response_model=List[AttendanceLogResponse],
    tags=["Attendance Query"]
)
def get_attendance_history(
    user_id_param: str,
    limit: int = Query(50, ge=1, le=500, description="Getirilecek maksimum kayıt sayısı"),
    current_user: dict = Depends(require_user)
):
    """
    Belirtilen çalışanın geçmiş mesai loglarını getirir.
    """
    actual_user_id, _ = get_resolved_user_id(user_id_param)
    ensure_can_access_user(current_user, actual_user_id)

    query_sql = """
        SELECT TOP (?) LogID, UserID, ActionType, LocationDescription, Latitude, Longitude, DeviceInfo, IPAddress, ResolvedAddress,
               -- [SERTIFIKA_MTLS_DEVRE_DISI] DeviceTrustStatus, DeviceCertificateDN, DeviceCertificateSerial, IsTrustedDevice,
               LogDateTime
        FROM FieldAttendanceLogs
        WHERE UserID = ?
        ORDER BY LogDateTime DESC, LogID DESC;
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query_sql, (limit, actual_user_id))
            rows = cursor.fetchall()

            result = []
            for row in rows:
                result.append(
                    AttendanceLogResponse(
                        LogID=row.LogID,
                        UserID=row.UserID,
                        ActionType=row.ActionType,
                        LocationDescription=row.LocationDescription,
                        Latitude=row.Latitude,
                        Longitude=row.Longitude,
                        DeviceInfo=row.DeviceInfo,
                        IPAddress=row.IPAddress,
                        ResolvedAddress=row.ResolvedAddress,
                        # [SERTIFIKA_MTLS_DEVRE_DISI]
                        # DeviceTrustStatus=getattr(row, "DeviceTrustStatus", None),
                        # DeviceCertificateDN=getattr(row, "DeviceCertificateDN", None),
                        # DeviceCertificateSerial=getattr(row, "DeviceCertificateSerial", None),
                        # IsTrustedDevice=bool(getattr(row, "IsTrustedDevice", False)),
                        LogDateTime=row.LogDateTime
                    )
                )
            return result
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")


# ==========================================
# ADMIN & AUTHENTICATION API ENDPOINTS
# ==========================================

@app.post(
    "/api/v1/auth/login",
    response_model=LoginResponse,
    tags=["Authentication"]
)
def login(payload: LoginRequest):
    """
    Kullanıcı (Çalışan) veya Admin şifreli giriş doğrulaması yapar.
    """
    code_val = payload.EmployeeCode.strip()

    # Veritabanı UserID'si iç anahtardır; girişte yalnızca Çalışan Kodu veya Ad Soyad kabul edilir
    query_sql = """
        SELECT UserID, EmployeeCode, FullName, CardUID, Password, Role, CreatedAt
        FROM Users
        WHERE EmployeeCode = ? OR LOWER(FullName) = LOWER(?);
    """
    params = (code_val, code_val)

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query_sql, params)
            rows = cursor.fetchall()
            
            target_user = None
            for row in rows:
                if verify_password(payload.Password, row.Password):
                    target_user = row
                    break

            if not target_user:
                return LoginResponse(
                    success=False,
                    message="Geçersiz çalışan adı/kodu veya şifre.",
                    user=None
                )

            # Eski düz metin şifreyi ilk başarılı girişte hashe yükselt
            if not is_password_hashed(target_user.Password):
                cursor.execute(
                    "UPDATE Users SET Password = ? WHERE UserID = ?;",
                    (hash_password(payload.Password), target_user.UserID)
                )
                conn.commit()

            return LoginResponse(
                success=True,
                message="Giriş başarılı.",
                token=create_access_token(target_user.UserID, target_user.Role),
                user=UserResponse(
                    UserID=target_user.UserID,
                    EmployeeCode=target_user.EmployeeCode,
                    FullName=target_user.FullName,
                    CardUID=target_user.CardUID,
                    Role=target_user.Role,
                    CreatedAt=target_user.CreatedAt
                )
            )
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")



@app.post(
    "/api/v1/auth/change-password",
    response_model=PasswordChangeResponse,
    tags=["Authentication"]
)
def change_own_password(payload: PasswordChangeRequest, current_user: dict = Depends(require_user)):
    """
    Giriş yapmış kullanıcı kendi şifresini değiştirir (mevcut şifre doğrulanır).
    Diğer cihazlardaki oturumlar kapanır; bu oturum yanıttaki yeni token ile devam eder.
    Hatalı mevcut şifre 400 döner (401 değil), böylece istemci oturumu kapatmaz.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT Password, Role FROM Users WHERE UserID = ?;", (current_user["uid"],))
            row = cursor.fetchone()
            if not row or not verify_password(payload.CurrentPassword, row.Password):
                raise HTTPException(status_code=400, detail="Mevcut şifre hatalı.")
            if verify_password(payload.NewPassword, row.Password):
                raise HTTPException(status_code=400, detail="Yeni şifre mevcut şifreyle aynı olamaz.")

            set_user_password(cursor, current_user["uid"], payload.NewPassword)
            conn.commit()

            return PasswordChangeResponse(
                message="Şifreniz değiştirildi. Diğer cihazlardaki oturumlarınız kapatıldı.",
                token=create_access_token(current_user["uid"], row.Role)
            )
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")


@app.post(
    "/api/v1/admin/users/{user_id}/password",
    response_model=MessageResponse,
    tags=["Admin Operations"]
)
def admin_set_user_password(user_id: int, payload: PasswordSetRequest, current_admin: dict = Depends(require_admin)):
    """
    Admin bir kullanıcıya yeni şifre belirler; kullanıcının açık oturumları kapanır.
    Admin kendi şifresini buradan değil, mevcut şifresini doğrulayan 'Şifremi Değiştir' akışından değiştirir.
    """
    if user_id == current_admin["uid"]:
        raise HTTPException(status_code=400, detail="Kendi şifrenizi 'Şifremi Değiştir' ekranından değiştiriniz.")

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if set_user_password(cursor, user_id, payload.NewPassword) == 0:
                raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")
            conn.commit()
            return MessageResponse(success=True, message="Şifre güncellendi. Kullanıcının açık oturumları kapatıldı.")
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")


@app.post(
    "/api/v1/admin/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin Operations"],
    dependencies=[Depends(require_admin)]
)
def create_user(payload: UserCreate):
    """
    Yeni kullanıcı/çalışan kaydı oluşturur ve MSSQL Users tablosuna kaydeder.
    """
    insert_sql = """
        INSERT INTO Users (EmployeeCode, FullName, CardUID, Password, Role, CreatedAt)
        OUTPUT INSERTED.UserID, INSERTED.EmployeeCode, INSERTED.FullName, 
               INSERTED.CardUID, INSERTED.Role, INSERTED.CreatedAt
        VALUES (?, ?, ?, ?, ?, GETDATE());
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                insert_sql,
                (
                    payload.EmployeeCode.strip(),
                    payload.FullName.strip(),
                    normalize_card_uid(payload.CardUID),
                    hash_password(payload.Password),
                    payload.Role
                )
            )
            row = cursor.fetchone()
            conn.commit()
            
            if not row:
                raise HTTPException(status_code=500, detail="Kullanıcı kaydı oluşturuldu ancak yanıt alınamadı.")

            return UserResponse(
                UserID=row.UserID,
                EmployeeCode=row.EmployeeCode,
                FullName=row.FullName,
                CardUID=row.CardUID,
                Role=row.Role,
                CreatedAt=row.CreatedAt
            )
    except pyodbc.IntegrityError:
        raise HTTPException(status_code=400, detail="Bu Çalışan Kodu veya RFID Kart UID zaten sistemde kayıtlı.")
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")


@app.get(
    "/api/v1/admin/users",
    response_model=List[UserResponse],
    tags=["Admin Operations"],
    dependencies=[Depends(require_admin)]
)
def list_users():
    """
    Sistemde kayıtlı tüm kullanıcıları listeler.
    """
    query_sql = """
        SELECT UserID, EmployeeCode, FullName, CardUID, Role, CreatedAt
        FROM Users
        ORDER BY UserID DESC;
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query_sql)
            rows = cursor.fetchall()
            
            result = []
            for row in rows:
                result.append(
                    UserResponse(
                        UserID=row.UserID,
                        EmployeeCode=row.EmployeeCode,
                        FullName=row.FullName,
                        CardUID=row.CardUID,
                        Role=row.Role,
                        CreatedAt=row.CreatedAt
                    )
                )
            return result
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")


@app.get(
    "/api/v1/admin/locations",
    response_model=List[LocationResponse],
    tags=["Admin Operations"],
    dependencies=[Depends(require_admin)]
)
@app.get(
    "/api/v1/locations",
    response_model=List[LocationResponse],
    tags=["Attendance Query"],
    include_in_schema=False
)
def list_locations():
    """
    MSSQL Locations tablosunda kayıtlı tüm aktif konumları getirir.
    """
    query_sql = """
        SELECT LocationID, Code, DisplayName, IsActive
        FROM Locations
        WHERE IsActive = 1
        ORDER BY LocationID ASC;
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query_sql)
            rows = cursor.fetchall()
            
            result = []
            for row in rows:
                result.append(
                    LocationResponse(
                        LocationID=row.LocationID,
                        Code=row.Code,
                        DisplayName=row.DisplayName,
                        IsActive=bool(row.IsActive)
                    )
                )
            return result
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")


@app.get(
    "/api/v1/admin/reports",
    response_model=List[AttendanceReportLog],
    tags=["Admin Operations"],
    dependencies=[Depends(require_admin)]
)
def get_attendance_reports(
    filter_type: str = Query("weekly", description="Filtreleme türü: 'daily' (Günlük), 'weekly' (Haftalık), 'monthly' (Aylık), 'all' (Tümü)")
):
    """
    Seçilen filtreye göre (Günlük / Haftalık / Aylık / Tümü) MSSQL veritabanından mesai hareketlerini getirir.
    """
    filter_clean = filter_type.lower().strip()
    
    date_condition = ""
    if filter_clean == "daily":
        date_condition = "WHERE a.LogDateTime >= CAST(GETDATE() AS DATE)"
    elif filter_clean == "weekly":
        date_condition = "WHERE a.LogDateTime >= DATEADD(day, -7, GETDATE())"
    elif filter_clean == "monthly":
        date_condition = "WHERE a.LogDateTime >= DATEADD(month, -1, GETDATE())"

    query_sql = f"""
        SELECT a.LogID, a.UserID, u.EmployeeCode, u.FullName AS EmployeeName,
               a.ActionType, a.LocationDescription, a.Latitude, a.Longitude,
               a.DeviceInfo, a.IPAddress, a.ResolvedAddress,
               -- [SERTIFIKA_MTLS_DEVRE_DISI] a.DeviceTrustStatus, a.DeviceCertificateDN, a.DeviceCertificateSerial, a.IsTrustedDevice,
               a.LogDateTime
        FROM FieldAttendanceLogs a
        LEFT JOIN Users u ON (a.UserID = u.UserID OR TRY_CAST(u.EmployeeCode AS INT) = a.UserID)
        {date_condition}
        ORDER BY a.LogDateTime DESC, a.LogID DESC;
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query_sql)
            rows = cursor.fetchall()

            result = []
            for row in rows:
                result.append(
                    AttendanceReportLog(
                        LogID=row.LogID,
                        UserID=row.UserID,
                        EmployeeCode=row.EmployeeCode or f"EMP-{row.UserID}",
                        EmployeeName=row.EmployeeName or f"Çalışan #{row.UserID}",
                        ActionType=row.ActionType,
                        LocationDescription=row.LocationDescription,
                        Latitude=row.Latitude,
                        Longitude=row.Longitude,
                        DeviceInfo=row.DeviceInfo,
                        IPAddress=row.IPAddress,
                        ResolvedAddress=row.ResolvedAddress,
                        # [SERTIFIKA_MTLS_DEVRE_DISI]
                        # DeviceTrustStatus=getattr(row, "DeviceTrustStatus", None),
                        # DeviceCertificateDN=getattr(row, "DeviceCertificateDN", None),
                        # DeviceCertificateSerial=getattr(row, "DeviceCertificateSerial", None),
                        # IsTrustedDevice=bool(getattr(row, "IsTrustedDevice", False)),
                        LogDateTime=row.LogDateTime
                    )
                )
            return result
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")


@app.get(
    "/api/v1/admin/reports/employee",
    response_model=EmployeeAttendanceReportResponse,
    tags=["Admin Operations"],
    dependencies=[Depends(require_admin)]
)
@app.get(
    "/api/admin/reports/employee",
    response_model=EmployeeAttendanceReportResponse,
    tags=["Admin Operations"],
    include_in_schema=False,
    dependencies=[Depends(require_admin)]
)
def get_employee_attendance_report(
    employeeId: Optional[str] = Query(None, description="Çalışan UserID veya EmployeeCode"),
    range: str = Query("weekly", description="Dönem filtresi: 'daily', 'weekly', 'monthly', 'custom'"),
    start_date: Optional[str] = Query(None, description="Özel tarih aralığı başlangıç (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Özel tarih aralığı bitiş (YYYY-MM-DD)")
):
    """
    Belirli bir çalışana ait mesai hareketlerini ve toplam tahmini çalışma saati özetini getirir.
    """
    if not employeeId or not str(employeeId).strip():
        return EmployeeAttendanceReportResponse(employee=None, records=[])

    actual_user_id, full_name = get_resolved_user_id(employeeId)

    str_emp_id = str(employeeId).strip()
    user_detail_sql = """
        SELECT TOP 1 UserID, EmployeeCode, FullName
        FROM Users
        WHERE UserID = ? OR EmployeeCode = ?
        ORDER BY CASE WHEN UserID = ? THEN 0 ELSE 1 END;
    """

    range_clean = range.lower().strip()
    where_clauses = ["(a.UserID = ? OR u.EmployeeCode = ?)"]
    params = [actual_user_id, str_emp_id]

    if range_clean == "daily":
        where_clauses.append("CAST(a.LogDateTime AS DATE) = CAST(GETDATE() AS DATE)")
    elif range_clean == "weekly":
        where_clauses.append("a.LogDateTime >= DATEADD(day, -7, GETDATE())")
    elif range_clean == "monthly":
        where_clauses.append("a.LogDateTime >= DATEADD(month, -1, GETDATE())")
    elif range_clean == "custom":
        if start_date:
            s_dt = start_date.strip()
            if len(s_dt) == 10:
                s_dt += " 00:00:00"
            where_clauses.append("a.LogDateTime >= ?")
            params.append(s_dt)
        if end_date:
            e_dt = end_date.strip()
            if len(e_dt) == 10:
                e_dt += " 23:59:59"
            where_clauses.append("a.LogDateTime <= ?")
            params.append(e_dt)

    where_sql = " WHERE " + " AND ".join(where_clauses)

    query_sql = f"""
        SELECT a.LogID, a.UserID, u.EmployeeCode, u.FullName AS EmployeeName,
               a.ActionType, a.LocationDescription, a.Latitude, a.Longitude,
               a.DeviceInfo, a.IPAddress, a.ResolvedAddress,
               -- [SERTIFIKA_MTLS_DEVRE_DISI] a.DeviceTrustStatus, a.DeviceCertificateDN, a.DeviceCertificateSerial, a.IsTrustedDevice,
               a.LogDateTime
        FROM FieldAttendanceLogs a
        LEFT JOIN Users u ON (a.UserID = u.UserID OR TRY_CAST(u.EmployeeCode AS INT) = a.UserID)
        {where_sql}
        ORDER BY a.LogDateTime DESC, a.LogID DESC;
    """

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(user_detail_sql, (actual_user_id, str(employeeId).strip(), actual_user_id))
            u_row = cursor.fetchone()
            emp_code = u_row.EmployeeCode if u_row else f"EMP-{actual_user_id}"
            emp_name = u_row.FullName if u_row else full_name

            cursor.execute(query_sql, params)
            rows = cursor.fetchall()

            records = []
            for row in rows:
                records.append(
                    AttendanceReportLog(
                        LogID=row.LogID,
                        UserID=row.UserID,
                        EmployeeCode=row.EmployeeCode or emp_code,
                        EmployeeName=row.EmployeeName or emp_name,
                        ActionType=row.ActionType,
                        LocationDescription=row.LocationDescription,
                        Latitude=row.Latitude,
                        Longitude=row.Longitude,
                        DeviceInfo=row.DeviceInfo,
                        IPAddress=row.IPAddress,
                        ResolvedAddress=row.ResolvedAddress,
                        # [SERTIFIKA_MTLS_DEVRE_DISI]
                        # DeviceTrustStatus=getattr(row, "DeviceTrustStatus", None),
                        # DeviceCertificateDN=getattr(row, "DeviceCertificateDN", None),
                        # DeviceCertificateSerial=getattr(row, "DeviceCertificateSerial", None),
                        # IsTrustedDevice=bool(getattr(row, "IsTrustedDevice", False)),
                        LogDateTime=row.LogDateTime
                    )
                )

            # Eşleşen CHECK_IN ve CHECK_OUT kayıtlarından çalışma saati hesaplama
            sorted_asc = sorted(records, key=lambda x: x.LogDateTime)
            total_seconds = 0.0
            last_in_time = None

            for log in sorted_asc:
                if log.ActionType == "CHECK_IN":
                    last_in_time = log.LogDateTime
                elif log.ActionType == "CHECK_OUT" and last_in_time is not None:
                    diff = (log.LogDateTime - last_in_time).total_seconds()
                    if diff > 0:
                        total_seconds += diff
                    last_in_time = None

            total_hours = round(total_seconds / 3600.0, 2)

            summary = EmployeeSummary(
                UserID=actual_user_id,
                EmployeeCode=emp_code,
                FullName=emp_name,
                total_records=len(records),
                total_work_hours=total_hours
            )

            return EmployeeAttendanceReportResponse(
                employee=summary,
                records=records
            )

    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")


# ==========================================
# KİOSK (KART OKUYUCU TERMİNAL) API
# ==========================================

# Aynı çalışanın art arda okutmaları bu süre içinde yeni kayıt oluşturmaz (çift okutma koruması)
KIOSK_DEBOUNCE_SECONDS = int(os.getenv("KIOSK_DEBOUNCE_SECONDS", "60"))
# Bu süreden eski açık giriş "çıkışı unutulmuş" sayılır; yeni okutma çıkış değil yeni giriş olur
KIOSK_STALE_CHECKIN_HOURS = float(os.getenv("KIOSK_STALE_CHECKIN_HOURS", "16"))


@app.get("/api/v1/kiosk/ping", response_model=KioskPingResponse, tags=["Kiosk"])
def kiosk_ping(request: Request, terminal: dict = Depends(require_terminal)):
    """
    Kiosk açılışta ve periyodik olarak çağırır: anahtarı doğrular, terminal adı ve konumunu döner,
    yönetim panelinde görünen 'son görülme' bilgisini günceller.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE Terminals SET LastSeenAt = GETDATE(), LastSeenIP = ? OUTPUT INSERTED.LastSeenAt WHERE TerminalID = ?;",
                (get_client_ip(request), terminal["terminal_id"])
            )
            row = cursor.fetchone()
            conn.commit()

            return KioskPingResponse(
                terminal_code=terminal["terminal_code"],
                terminal_name=terminal["terminal_name"],
                location=terminal["location_name"],
                server_time=row.LastSeenAt
            )
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")


@app.post("/api/v1/kiosk/punch", response_model=KioskPunchResponse, tags=["Kiosk"])
def kiosk_punch(payload: KioskPunchRequest, request: Request, terminal: dict = Depends(require_terminal)):
    """
    Kart okutma: çalışanın son hareketine göre giriş veya çıkış kaydeder.
    Saat, konum ve cihaz bilgisi istemciden değil sunucu ve terminal kaydından alınır.
    İş sonuçları (tanınmayan kart, çok erken okutma dahil) 200 ile 'result' alanında döner.
    """
    card_uid = normalize_card_uid(payload.CardUID)
    if not card_uid:
        raise HTTPException(status_code=422, detail="Kart UID boş olamaz.")

    terminal_id = terminal["terminal_id"]
    location = terminal["location_name"] or terminal["terminal_name"]
    device_info = f"Kiosk: {terminal['terminal_code']} - {terminal['terminal_name']}"[:255]

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE Terminals SET LastSeenAt = GETDATE(), LastSeenIP = ? WHERE TerminalID = ?;",
                (get_client_ip(request), terminal_id)
            )

            cursor.execute("SELECT UserID, EmployeeCode, FullName FROM Users WHERE CardUID = ?;", (card_uid,))
            user = cursor.fetchone()
            if not user:
                # Yöneticinin yeni kart tanımlarken okuyucunun gönderdiği UID'yi panelden görebilmesi için saklanır
                cursor.execute(
                    "UPDATE Terminals SET LastUnknownCardUID = ?, LastUnknownCardAt = GETDATE() WHERE TerminalID = ?;",
                    (card_uid[:50], terminal_id)
                )
                conn.commit()
                return KioskPunchResponse(
                    result="UNKNOWN_CARD",
                    message="Kart tanınmadı. Lütfen yöneticinize başvurunuz.",
                    location=location
                )

            # UPDLOCK/HOLDLOCK: aynı çalışanın eşzamanlı okutmaları (iki terminal, çift okutma) sırayla işlenir
            cursor.execute(
                """
                SELECT TOP 1 ActionType, LogDateTime, DATEDIFF(SECOND, LogDateTime, GETDATE()) AS SecDiff
                FROM FieldAttendanceLogs WITH (UPDLOCK, HOLDLOCK)
                WHERE UserID = ?
                ORDER BY LogDateTime DESC, LogID DESC;
                """,
                (user.UserID,)
            )
            last = cursor.fetchone()
            sec_since_last = max(0, last.SecDiff) if last else None

            if last and sec_since_last < KIOSK_DEBOUNCE_SECONDS:
                conn.commit()
                wait = KIOSK_DEBOUNCE_SECONDS - sec_since_last
                already = "Girişiniz" if last.ActionType == "CHECK_IN" else "Çıkışınız"
                return KioskPunchResponse(
                    result="TOO_SOON",
                    message=f"{already} zaten kaydedildi. Tekrar okutmak için {wait} saniye bekleyiniz.",
                    employee_name=user.FullName,
                    employee_code=user.EmployeeCode,
                    action_time=last.LogDateTime,
                    last_action=last.ActionType,
                    retry_after_seconds=wait,
                    location=location
                )

            warning = None
            if last and last.ActionType == "CHECK_IN" and sec_since_last < KIOSK_STALE_CHECKIN_HOURS * 3600:
                action = "CHECK_OUT"
            else:
                action = "CHECK_IN"
                if last and last.ActionType == "CHECK_IN":
                    warning = "MISSING_CHECKOUT"

            cursor.execute(
                """
                INSERT INTO FieldAttendanceLogs (UserID, ActionType, LocationDescription, DeviceInfo, IPAddress, TerminalID, LogDateTime)
                OUTPUT INSERTED.LogDateTime
                VALUES (?, ?, ?, ?, ?, ?, GETDATE());
                """,
                (user.UserID, action, location, device_info, get_client_ip(request), terminal_id)
            )
            log_time = cursor.fetchone().LogDateTime
            conn.commit()

            if action == "CHECK_IN":
                message = f"Giriş kaydedildi. Hoş geldiniz, {user.FullName}."
                if warning:
                    message += " Önceki girişinizin çıkışı yapılmamış; lütfen yöneticinize bildiriniz."
            else:
                message = f"Çıkış kaydedildi. İyi günler, {user.FullName}."

            return KioskPunchResponse(
                result=action,
                message=message,
                employee_name=user.FullName,
                employee_code=user.EmployeeCode,
                action_time=log_time,
                warning=warning,
                location=location
            )
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")


KIOSK_PAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kiosk", "kiosk.html")


@app.get("/kiosk/download", include_in_schema=False)
def download_kiosk_page():
    """
    Kiosk ekranını (kiosk.html) indirme olarak sunar. Gizli bilgi içermez (anahtar ve sunucu adresi config.js'tedir);
    bu yüzden herkese açıktır. Sayfa olarak değil dosya olarak verilir: kiosk.html yanındaki config.js ile çalışır.
    """
    return FileResponse(KIOSK_PAGE_PATH, media_type="text/html", filename="kiosk.html")


# ==========================================
# ADMIN: KİOSK TERMİNAL YÖNETİMİ
# ==========================================

TERMINAL_SELECT_SQL = """
    SELECT t.TerminalID, t.TerminalCode, t.TerminalName, t.LocationID, l.DisplayName AS LocationName,
           t.IsActive, CASE WHEN t.TerminalKeyHash IS NULL THEN 0 ELSE 1 END AS HasKey,
           t.LastSeenAt, t.LastSeenIP, t.LastUnknownCardUID, t.LastUnknownCardAt, t.CreatedAt
    FROM Terminals t
    LEFT JOIN Locations l ON l.LocationID = t.LocationID
"""


def fetch_terminal(cursor, terminal_id: int) -> TerminalResponse:
    cursor.execute(TERMINAL_SELECT_SQL + " WHERE t.TerminalID = ?;", (terminal_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Terminal bulunamadı.")
    return terminal_from_row(row)


def terminal_from_row(row) -> TerminalResponse:
    return TerminalResponse(
        TerminalID=row.TerminalID,
        TerminalCode=row.TerminalCode,
        TerminalName=row.TerminalName,
        LocationID=row.LocationID,
        LocationName=row.LocationName,
        IsActive=bool(row.IsActive),
        HasKey=bool(row.HasKey),
        LastSeenAt=row.LastSeenAt,
        LastSeenIP=row.LastSeenIP,
        LastUnknownCardUID=row.LastUnknownCardUID,
        LastUnknownCardAt=row.LastUnknownCardAt,
        CreatedAt=row.CreatedAt
    )


@app.get(
    "/api/v1/admin/terminals",
    response_model=List[TerminalResponse],
    tags=["Admin Operations"],
    dependencies=[Depends(require_admin)]
)
def list_terminals():
    """Kayıtlı kiosk terminallerini durum ve son görülme bilgileriyle listeler."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(TERMINAL_SELECT_SQL + " ORDER BY t.TerminalID ASC;")
            return [terminal_from_row(row) for row in cursor.fetchall()]
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")


@app.post(
    "/api/v1/admin/terminals",
    response_model=TerminalKeyResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin Operations"],
    dependencies=[Depends(require_admin)]
)
def create_terminal(payload: TerminalCreate):
    """Yeni kiosk terminali oluşturur. Terminal anahtarı yalnızca bu yanıtta bir kez döner."""
    terminal_key = generate_terminal_key()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO Terminals (TerminalCode, TerminalName, LocationID, TerminalType, TerminalKeyHash, IsActive, CreatedAt)
                OUTPUT INSERTED.TerminalID
                VALUES (?, ?, ?, 'KIOSK', ?, 1, GETDATE());
                """,
                (payload.TerminalCode.strip(), payload.TerminalName.strip(), payload.LocationID, hash_terminal_key(terminal_key))
            )
            terminal_id = cursor.fetchone().TerminalID
            conn.commit()
            return TerminalKeyResponse(terminal=fetch_terminal(cursor, terminal_id), TerminalKey=terminal_key)
    except pyodbc.IntegrityError:
        raise HTTPException(status_code=400, detail="Bu terminal kodu zaten kayıtlı veya seçilen konum geçersiz.")
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")


@app.post(
    "/api/v1/admin/terminals/{terminal_id}/key",
    response_model=TerminalKeyResponse,
    tags=["Admin Operations"],
    dependencies=[Depends(require_admin)]
)
def regenerate_terminal_key(terminal_id: int):
    """Terminal için yeni anahtar üretir; eski anahtar anında geçersiz olur. Yeni anahtar yalnızca bu yanıtta döner."""
    terminal_key = generate_terminal_key()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE Terminals SET TerminalKeyHash = ? WHERE TerminalID = ?;",
                (hash_terminal_key(terminal_key), terminal_id)
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Terminal bulunamadı.")
            conn.commit()
            return TerminalKeyResponse(terminal=fetch_terminal(cursor, terminal_id), TerminalKey=terminal_key)
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")


@app.patch(
    "/api/v1/admin/terminals/{terminal_id}",
    response_model=TerminalResponse,
    tags=["Admin Operations"],
    dependencies=[Depends(require_admin)]
)
def update_terminal(terminal_id: int, payload: TerminalUpdate):
    """Terminali etkinleştirir veya devre dışı bırakır. Devre dışı terminalin anahtarı kabul edilmez."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE Terminals SET IsActive = ? WHERE TerminalID = ?;",
                (1 if payload.IsActive else 0, terminal_id)
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Terminal bulunamadı.")
            conn.commit()
            return fetch_terminal(cursor, terminal_id)
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
