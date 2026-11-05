import os
import io
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from typing import List, Optional, Union
import pyodbc
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from database import get_db_connection
from auth import (
    hash_password, verify_password, is_password_hashed, create_access_token, require_admin, require_user,
    require_terminal, generate_terminal_key, hash_terminal_key, set_user_password, decode_access_token
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
    MessageResponse,
    PersonnelWorkHoursItem,
    PersonnelWorkHoursReportResponse,
    LiveMapItem,
    LiveMapResponse
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


@app.get("/reports", include_in_schema=False)
def read_reports_page():
    """
    Tüm personellerin çalışma saatlerini ve Excel raporlama arayüzünü (reports.html) sunar.
    """
    return FileResponse("static/reports.html")


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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")


# ==========================================
# PERSONEL TOPLU ÇALIŞMA SAATLERİ VE EXCEL RAPORLAMA API
# ==========================================

def require_admin_or_query_token(
    request: Request,
    token: Optional[str] = Query(None, description="Opsiyonel indirme token'ı")
) -> dict:
    """Excel indirmelerinde hem Authorization Header hem de URL ?token=... desteği sağlar."""
    auth_header = request.headers.get("Authorization")
    raw_token = None
    if auth_header and auth_header.startswith("Bearer "):
        raw_token = auth_header.split(" ", 1)[1].strip()
    elif token:
        raw_token = token.strip()
    
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Oturum token'ı bulunamadı.")
    
    payload = decode_access_token(raw_token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz veya süresi dolmuş oturum token'ı.")
    if payload.get("role") != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için Admin yetkisi gereklidir.")
    return payload


def _fetch_work_hours_report_data(
    range_type: str = "weekly",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None
) -> tuple[PersonnelWorkHoursReportResponse, list]:
    range_clean = (range_type or "weekly").lower().strip()

    date_clauses = []
    date_params = []

    if range_clean == "daily":
        date_clauses.append("CAST(a.LogDateTime AS DATE) = CAST(GETDATE() AS DATE)")
    elif range_clean == "weekly":
        date_clauses.append("a.LogDateTime >= DATEADD(day, -7, GETDATE())")
    elif range_clean == "monthly":
        date_clauses.append("a.LogDateTime >= DATEADD(month, -1, GETDATE())")
    elif range_clean == "custom":
        if start_date and start_date.strip():
            s = start_date.strip()
            if len(s) == 10:
                s += " 00:00:00"
            date_clauses.append("a.LogDateTime >= ?")
            date_params.append(s)
        if end_date and end_date.strip():
            e = end_date.strip()
            if len(e) == 10:
                e += " 23:59:59"
            date_clauses.append("a.LogDateTime <= ?")
            date_params.append(e)

    date_where_sql = ("WHERE " + " AND ".join(date_clauses)) if date_clauses else ""

    users_sql = """
        SELECT UserID, EmployeeCode, FullName, Role, CardUID
        FROM Users
        ORDER BY FullName ASC;
    """

    logs_sql = f"""
        SELECT a.LogID, a.UserID, u.UserID AS MatchedUserID, u.EmployeeCode, u.FullName,
               a.ActionType, a.LocationDescription, a.Latitude, a.Longitude,
               a.DeviceInfo, a.IPAddress, a.ResolvedAddress, a.LogDateTime
        FROM FieldAttendanceLogs a
        LEFT JOIN Users u ON a.UserID = u.UserID
        {date_where_sql}
        ORDER BY a.LogDateTime ASC, a.LogID ASC;
    """

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(users_sql)
        user_rows = cursor.fetchall()

        cursor.execute(logs_sql, date_params)
        log_rows = cursor.fetchall()

    import collections
    logs_by_user = collections.defaultdict(list)
    all_logs_list = []

    for row in log_rows:
        resolved_uid = row.MatchedUserID if row.MatchedUserID is not None else row.UserID
        log_obj = AttendanceReportLog(
            LogID=row.LogID,
            UserID=row.UserID,
            EmployeeCode=row.EmployeeCode or f"EMP-{row.UserID}",
            EmployeeName=row.FullName or f"Çalışan #{row.UserID}",
            ActionType=row.ActionType or "CHECK_IN",
            LocationDescription=row.LocationDescription or "-",
            Latitude=row.Latitude,
            Longitude=row.Longitude,
            DeviceInfo=row.DeviceInfo,
            IPAddress=row.IPAddress,
            ResolvedAddress=row.ResolvedAddress,
            LogDateTime=row.LogDateTime
        )
        logs_by_user[resolved_uid].append(log_obj)
        all_logs_list.append(log_obj)

    search_term = (search or "").strip().lower()

    items: List[PersonnelWorkHoursItem] = []
    total_hours_sum = 0.0
    active_now_count = 0
    now_dt = datetime.now()

    for u in user_rows:
        if search_term:
            emp_c = (u.EmployeeCode or "").lower()
            emp_n = (u.FullName or "").lower()
            if search_term not in emp_c and search_term not in emp_n:
                continue

        u_logs = logs_by_user.get(u.UserID, [])

        check_ins = sum(1 for l in u_logs if l.ActionType == "CHECK_IN")
        check_outs = sum(1 for l in u_logs if l.ActionType == "CHECK_OUT")
        days_worked = len(set(l.LogDateTime.date() for l in u_logs if l.LogDateTime is not None))
        
        first_log = u_logs[0] if u_logs else None
        last_log = u_logs[-1] if u_logs else None
        first_punch = first_log.LogDateTime if first_log else None
        last_punch = last_log.LogDateTime if last_log else None

        total_seconds = 0.0
        last_checkin_time = None
        for l in u_logs:
            if not l.LogDateTime:
                continue
            if l.ActionType == "CHECK_IN":
                last_checkin_time = l.LogDateTime
            elif l.ActionType == "CHECK_OUT" and last_checkin_time is not None:
                diff = (l.LogDateTime - last_checkin_time).total_seconds()
                if 0 < diff <= 24 * 3600:
                    total_seconds += diff
                last_checkin_time = None

        total_work_hours = round(total_seconds / 3600.0, 2)
        total_hours_sum += total_work_hours

        hours_int = int(total_seconds // 3600)
        mins_int = int((total_seconds % 3600) // 60)
        formatted_duration = f"{hours_int} sa {mins_int} dk" if total_seconds > 0 else "0 sa 0 dk"

        is_currently_active = bool(
            last_log and last_log.ActionType == "CHECK_IN" and last_log.LogDateTime and (now_dt - last_log.LogDateTime).total_seconds() < 18 * 3600
        )
        if is_currently_active:
            active_now_count += 1

        items.append(
            PersonnelWorkHoursItem(
                UserID=u.UserID,
                EmployeeCode=str(u.EmployeeCode or f"EMP-{u.UserID}"),
                FullName=str(u.FullName or f"Çalışan #{u.UserID}"),
                Role=str(u.Role or "EMPLOYEE"),
                TotalCheckIns=check_ins,
                TotalCheckOuts=check_outs,
                DaysWorked=days_worked,
                TotalWorkSeconds=total_seconds,
                TotalWorkHours=total_work_hours,
                FormattedWorkDuration=formatted_duration,
                FirstPunch=first_punch,
                LastPunch=last_punch,
                IsCurrentlyActive=is_currently_active
            )
        )

    # Çok çalışandan aza doğru sıralama
    items.sort(key=lambda x: (-x.TotalWorkHours, x.FullName.lower()))

    total_personnel_count = len(items)
    avg_hours = round(total_hours_sum / total_personnel_count, 2) if total_personnel_count > 0 else 0.0

    report_response = PersonnelWorkHoursReportResponse(
        filter_range=range_clean,
        start_date=start_date,
        end_date=end_date,
        total_personnel_count=total_personnel_count,
        total_active_personnel=active_now_count,
        total_hours_sum=round(total_hours_sum, 2),
        average_hours=avg_hours,
        items=items
    )

    return report_response, all_logs_list


def create_work_hours_excel_file(report_data: PersonnelWorkHoursReportResponse, all_logs: list, period_label: str) -> io.BytesIO:
    """Openpyxl kullanarak profesyonel, çift sayfalı Excel çalışma kitabı üretir."""
    wb = openpyxl.Workbook()

    COLOR_HEADER_BG = "2E5B3E"      # Derin zümrüt yeşili
    COLOR_HEADER_TEXT = "FFFFFF"
    COLOR_ZEBRA = "F4F7F4"
    COLOR_BORDER = "D1D5DB"
    COLOR_TOTAL_BG = "E5E7EB"

    thin_side = Side(border_style="thin", color=COLOR_BORDER)
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    double_bottom_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=Side(border_style="double", color="111827"))

    # 1. SAYFA: PERSONEL ÇALIŞMA SÜRELERİ ÖZETİ
    ws1 = wb.active
    ws1.title = "Personel Çalışma Saatleri"
    ws1.views.sheetView[0].showGridLines = True

    # Başlık Bloğu
    ws1.merge_cells("A1:L1")
    title_cell = ws1["A1"]
    title_cell.value = "SAHA MESAİ TAKİP - PERSONEL ÇALIŞMA SÜRELERİ RAPORU"
    title_cell.font = Font(name="Calibri", size=14, bold=True, color=COLOR_HEADER_TEXT)
    title_cell.fill = PatternFill(start_color=COLOR_HEADER_BG, end_color=COLOR_HEADER_BG, fill_type="solid")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[1].height = 36

    # Bilgi Satırı
    ws1["A2"] = "Filtre Periyodu:"
    ws1["B2"] = period_label
    ws1["A2"].font = Font(name="Calibri", size=10, bold=True)
    ws1["D2"] = "Rapor Alma Tarihi:"
    ws1["E2"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    ws1["D2"].font = Font(name="Calibri", size=10, bold=True)
    ws1.row_dimensions[2].height = 20

    # Özet İstatistik Satırı
    ws1.merge_cells("A3:L3")
    kpi_cell = ws1["A3"]
    kpi_cell.value = f"Toplam Personel: {report_data.total_personnel_count}  |  Anlık Mesaide: {report_data.total_active_personnel}  |  Toplam Mesai: {report_data.total_hours_sum} Saat  |  Personel Başına Ortalama: {report_data.average_hours} Saat"
    kpi_cell.font = Font(name="Calibri", size=10, italic=True, color="374151")
    kpi_cell.fill = PatternFill(start_color="F0F4F1", end_color="F0F4F1", fill_type="solid")
    kpi_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[3].height = 22

    # Tablo Başlıkları (Satır 5)
    headers = [
        "Sıra", "Sicil Kodu", "Personel Adı Soyadı", "Rol / Yetki", "Çalışılan Gün",
        "Giriş Sayısı", "Çıkış Sayısı", "Toplam Süre (Saat)", "Toplam Süre (Metin)",
        "Anlık Durum", "İlk Hareket", "Son Hareket"
    ]
    ws1.row_dimensions[5].height = 26
    for col_idx, header in enumerate(headers, 1):
        cell = ws1.cell(row=5, column=col_idx, value=header)
        cell.font = Font(name="Calibri", size=11, bold=True, color=COLOR_HEADER_TEXT)
        cell.fill = PatternFill(start_color=COLOR_HEADER_BG, end_color=COLOR_HEADER_BG, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = cell_border

    # Satırlar
    start_row = 6
    for idx, item in enumerate(report_data.items, 1):
        current_row = start_row + idx - 1
        ws1.row_dimensions[current_row].height = 20
        is_zebra = (idx % 2 == 0)
        row_fill = PatternFill(start_color=COLOR_ZEBRA, end_color=COLOR_ZEBRA, fill_type="solid") if is_zebra else None

        status_str = "Mesaide (Giriş)" if item.IsCurrentlyActive else "Dışarıda"
        first_punch_str = item.FirstPunch.strftime("%d.%m.%Y %H:%M") if item.FirstPunch else "-"
        last_punch_str = item.LastPunch.strftime("%d.%m.%Y %H:%M") if item.LastPunch else "-"

        row_values = [
            idx,
            item.EmployeeCode,
            item.FullName,
            item.Role,
            item.DaysWorked,
            item.TotalCheckIns,
            item.TotalCheckOuts,
            item.TotalWorkHours,
            item.FormattedWorkDuration,
            status_str,
            first_punch_str,
            last_punch_str
        ]

        for col_idx, val in enumerate(row_values, 1):
            cell = ws1.cell(row=current_row, column=col_idx, value=val)
            if row_fill:
                cell.fill = row_fill
            cell.border = cell_border
            cell.font = Font(name="Calibri", size=10)

            if col_idx in (1, 5, 6, 7):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 8:
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "#,##0.00"
            elif col_idx in (10, 11, 12):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    # Genel Toplam Satırı
    last_data_row = start_row + len(report_data.items) - 1
    total_row = max(start_row, last_data_row + 1)
    ws1.row_dimensions[total_row].height = 24

    ws1.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=4)
    total_label = ws1.cell(row=total_row, column=1, value="GENEL TOPLAM")
    total_label.font = Font(name="Calibri", size=11, bold=True)
    total_label.alignment = Alignment(horizontal="center", vertical="center")

    for c in range(1, 13):
        cell = ws1.cell(row=total_row, column=c)
        cell.fill = PatternFill(start_color=COLOR_TOTAL_BG, end_color=COLOR_TOTAL_BG, fill_type="solid")
        cell.border = double_bottom_border

    if len(report_data.items) > 0:
        ws1.cell(row=total_row, column=5, value=f"=SUM(E{start_row}:E{last_data_row})").font = Font(bold=True)
        ws1.cell(row=total_row, column=6, value=f"=SUM(F{start_row}:F{last_data_row})").font = Font(bold=True)
        ws1.cell(row=total_row, column=7, value=f"=SUM(G{start_row}:G{last_data_row})").font = Font(bold=True)
        h_cell = ws1.cell(row=total_row, column=8, value=f"=SUM(H{start_row}:H{last_data_row})")
        h_cell.font = Font(bold=True)
        h_cell.number_format = "#,##0.00"
        for col_c in (5, 6, 7):
            ws1.cell(row=total_row, column=col_c).alignment = Alignment(horizontal="center", vertical="center")
        h_cell.alignment = Alignment(horizontal="right", vertical="center")

    # Kolon genişliklerini otomatik ayarla
    for col in ws1.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.row in (1, 3):
                continue
            val_str = str(cell.value or "")
            if val_str.startswith("="):
                val_str = "9999.00"
            max_len = max(max_len, len(val_str))
        ws1.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # 2. SAYFA: DETAYLI MESAI HAREKET LOGLARI
    ws2 = wb.create_sheet(title="Mesai Hareketleri")
    ws2.views.sheetView[0].showGridLines = True

    log_headers = ["Log ID", "Sicil Kodu", "Personel Adı Soyadı", "İşlem Türü", "Tarih & Saat", "Konum / Şantiye", "Açık Adres", "Cihaz Bilgisi", "IP Adresi"]
    ws2.row_dimensions[1].height = 25
    for col_idx, h in enumerate(log_headers, 1):
        c = ws2.cell(row=1, column=col_idx, value=h)
        c.font = Font(name="Calibri", size=11, bold=True, color=COLOR_HEADER_TEXT)
        c.fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = cell_border

    for idx, log in enumerate(all_logs, 2):
        ws2.row_dimensions[idx].height = 18
        is_zebra = (idx % 2 == 0)
        row_fill = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid") if is_zebra else None

        action_tr = "GİRİŞ" if log.ActionType == "CHECK_IN" else "ÇIKIŞ"
        date_str = log.LogDateTime.strftime("%d.%m.%Y %H:%M:%S") if log.LogDateTime else "-"

        vals = [
            log.LogID,
            log.EmployeeCode or f"EMP-{log.UserID}",
            log.EmployeeName or f"Çalışan #{log.UserID}",
            action_tr,
            date_str,
            log.LocationDescription or "-",
            log.ResolvedAddress or "-",
            log.DeviceInfo or "-",
            log.IPAddress or "-"
        ]
        for c_idx, v in enumerate(vals, 1):
            cell = ws2.cell(row=idx, column=c_idx, value=v)
            if row_fill:
                cell.fill = row_fill
            cell.border = cell_border
            cell.font = Font(name="Calibri", size=10)
            if c_idx in (1, 4, 5, 9):
                cell.alignment = Alignment(horizontal="center", vertical="center")

    for col in ws2.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


@app.get(
    "/api/v1/admin/reports/work-hours",
    response_model=PersonnelWorkHoursReportResponse,
    tags=["Admin Operations"],
    dependencies=[Depends(require_admin)]
)
def get_personnel_work_hours(
    range: str = Query("weekly", description="Filtre türü: 'daily', 'weekly', 'monthly', 'custom', 'all'"),
    start_date: Optional[str] = Query(None, description="Başlangıç tarihi (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Bitiş tarihi (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="İsim veya Sicil Kodu ile arama")
):
    """
    Tüm personellerin seçilen tarih filtresine göre toplam ve tahmini çalışma saatlerini,
    giriş-çıkış istatistiklerini getirir.
    """
    try:
        report, _ = _fetch_work_hours_report_data(
            range_type=range,
            start_date=start_date,
            end_date=end_date,
            search=search
        )
        return report
    except pyodbc.Error as db_err:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")


@app.get(
    "/api/v1/admin/reports/work-hours/export-excel",
    tags=["Admin Operations"]
)
def export_personnel_work_hours_excel(
    request: Request,
    range: str = Query("weekly", description="Filtre türü: 'daily', 'weekly', 'monthly', 'custom', 'all'"),
    start_date: Optional[str] = Query(None, description="Başlangıç tarihi (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Bitiş tarihi (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="İsim veya Sicil Kodu ile arama"),
    token: Optional[str] = Query(None, description="Yetki token'ı"),
    admin: dict = Depends(require_admin_or_query_token)
):
    """
    Filtrelenen personel çalışma saatlerini ve mesai loglarını çift sayfalı şık bir Excel (.xlsx) dosyası olarak indirir.
    """
    try:
        report, all_logs = _fetch_work_hours_report_data(
            range_type=range,
            start_date=start_date,
            end_date=end_date,
            search=search
        )

        period_labels = {
            "daily": "Bugün",
            "weekly": "Son 7 Gün (Haftalık)",
            "monthly": "Son 30 Gün (Aylık)",
            "all": "Tüm Zamanlar",
            "custom": f"{start_date or '...'} - {end_date or '...'}"
        }
        period_text = period_labels.get(range.lower(), range)

        excel_stream = create_work_hours_excel_file(report, all_logs, period_text)
        file_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Personel_Mesai_Raporu_{range}_{file_stamp}.xlsx"

        return StreamingResponse(
            excel_stream,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except pyodbc.Error as db_err:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Excel oluşturulurken hata: {str(e)}")


# ==========================================
# CANLI SAHA & KONUM HARİTASI API
# ==========================================

@app.get(
    "/api/v1/admin/live-map",
    response_model=LiveMapResponse,
    tags=["Admin Operations"],
    dependencies=[Depends(require_admin)]
)
def get_live_map_data(
    filter_mode: str = Query("today", description="Zaman aralığı: 'today' (Bugün), 'last_24h' (Son 24 Saat), 'all_latest' (Tüm Son Konumlar)"),
    status: str = Query("all", description="Durum filtresi: 'all' (Tümü), 'active' (Sadece Mesaidekiler), 'completed' (Çıkış Yapanlar)")
):
    """
    Saha çalışanlarının en son mesai hareketlerini ve GPS koordinatlarını döner.
    Canlı harita üzerinde personelin anlık konumlarını ve durumlarını görselleştirmek için kullanılır.
    """
    mode_clean = (filter_mode or "today").lower().strip()
    status_clean = (status or "all").lower().strip()

    date_filter = ""
    if mode_clean == "today":
        date_filter = "WHERE a.LogDateTime >= CAST(GETDATE() AS DATE)"
    elif mode_clean == "last_24h":
        date_filter = "WHERE a.LogDateTime >= DATEADD(hour, -24, GETDATE())"

    query_sql = f"""
        WITH RankedLogs AS (
            SELECT 
                a.LogID, 
                a.UserID, 
                a.ActionType, 
                a.LocationDescription, 
                a.Latitude, 
                a.Longitude,
                a.DeviceInfo, 
                a.IPAddress, 
                a.ResolvedAddress, 
                a.LogDateTime,
                ROW_NUMBER() OVER (PARTITION BY a.UserID ORDER BY a.LogDateTime DESC, a.LogID DESC) AS rn
            FROM FieldAttendanceLogs a
            {date_filter}
        )
        SELECT 
            r.LogID, 
            r.UserID, 
            u.EmployeeCode, 
            u.FullName, 
            u.Role,
            r.ActionType, 
            r.LocationDescription, 
            r.Latitude, 
            r.Longitude,
            r.DeviceInfo, 
            r.IPAddress, 
            r.ResolvedAddress, 
            r.LogDateTime
        FROM RankedLogs r
        LEFT JOIN Users u ON r.UserID = u.UserID
        WHERE r.rn = 1
        ORDER BY r.LogDateTime DESC;
    """

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query_sql)
            rows = cursor.fetchall()

        now_dt = datetime.now()
        items: List[LiveMapItem] = []
        with_coords_count = 0
        without_coords_count = 0
        active_count = 0

        def _safe_parse_dt(dt_val) -> Optional[datetime]:
            if isinstance(dt_val, datetime):
                return dt_val
            if isinstance(dt_val, str) and dt_val.strip():
                cleaned = dt_val.strip()
                if "." in cleaned:
                    base, frac = cleaned.split(".", 1)
                    cleaned = base + "." + frac[:6]
                try:
                    return datetime.fromisoformat(cleaned)
                except Exception:
                    try:
                        return datetime.strptime(cleaned.split(".")[0], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        return None
            return None

        for r in rows:
            # Koordinatları güvenli float'a çevir
            lat = None
            lng = None
            try:
                if r.Latitude is not None:
                    lat = float(r.Latitude)
                if r.Longitude is not None:
                    lng = float(r.Longitude)
            except (ValueError, TypeError):
                pass

            has_coords = bool(lat is not None and lng is not None and (abs(lat) > 0.0001 or abs(lng) > 0.0001))
            if has_coords:
                with_coords_count += 1
            else:
                without_coords_count += 1

            log_dt = _safe_parse_dt(r.LogDateTime) or now_dt
            mins_ago = 0
            diff_sec = (now_dt - log_dt).total_seconds()
            mins_ago = max(0, int(diff_sec // 60))

            is_active = bool(
                r.ActionType == "CHECK_IN" and (now_dt - log_dt).total_seconds() < 18 * 3600
            )
            if is_active:
                active_count += 1

            if status_clean == "active" and not is_active:
                continue
            if status_clean == "completed" and is_active:
                continue

            time_str = log_dt.strftime("%H:%M")

            items.append(
                LiveMapItem(
                    LogID=r.LogID,
                    UserID=r.UserID,
                    EmployeeCode=str(r.EmployeeCode or f"EMP-{r.UserID}"),
                    FullName=str(r.FullName or f"Çalışan #{r.UserID}"),
                    Role=str(r.Role or "EMPLOYEE"),
                    ActionType=r.ActionType or "CHECK_IN",
                    LocationDescription=r.LocationDescription or "-",
                    Latitude=lat,
                    Longitude=lng,
                    DeviceInfo=r.DeviceInfo or "-",
                    IPAddress=r.IPAddress or "-",
                    ResolvedAddress=r.ResolvedAddress or "-",
                    LogDateTime=log_dt,
                    IsCurrentlyActive=is_active,
                    MinutesAgo=mins_ago,
                    TimeFormatted=time_str,
                    HasCoordinates=has_coords
                )
            )

        return LiveMapResponse(
            filter_mode=mode_clean,
            server_time=now_dt,
            total_personnel_reported=len(items),
            with_coordinates_count=with_coords_count,
            without_coordinates_count=without_coords_count,
            currently_active_count=active_count,
            items=items
        )

    except pyodbc.Error as db_err:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(db_err)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
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
