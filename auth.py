import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, HTTPException, status
from dotenv import load_dotenv

from database import get_db_connection

load_dotenv(override=True)

# ==========================================
# ŞİFRE HASHLEME (PBKDF2-SHA256)
# ==========================================

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def hash_password(password: str) -> str:
    """
    Şifreyi 'pbkdf2_sha256$iterasyon$salt$hash' formatında hashler (Users.Password NVARCHAR(255) içine sığar).
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${_b64e(salt)}${_b64e(digest)}"


def is_password_hashed(stored: Optional[str]) -> bool:
    return bool(stored) and stored.startswith(PASSWORD_SCHEME + "$")


def verify_password(password: str, stored: Optional[str]) -> bool:
    """
    Girilen şifreyi veritabanındaki değerle sabit zamanlı karşılaştırır.
    Henüz hashlenmemiş (eski düz metin) kayıtlar da desteklenir; login sırasında hashe yükseltilir.
    """
    if not stored:
        return False

    if not is_password_hashed(stored):
        return hmac.compare_digest(password.encode("utf-8"), stored.encode("utf-8"))

    try:
        _, iterations, salt_b64, hash_b64 = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _b64d(salt_b64), int(iterations))
        return hmac.compare_digest(digest, _b64d(hash_b64))
    except (ValueError, TypeError):
        return False


def set_user_password(cursor, user_id: int, new_password: str) -> int:
    """
    Kullanıcının şifresini hashleyerek günceller ve PasswordChangedAt'i işaretler; böylece bu andan önce
    açılmış tüm oturumlar geçersiz olur. Zaman veritabanının değil uygulamanın saatinden (UTC) alınır,
    çünkü token'lardaki 'iat' de uygulama saatidir. Güncellenen satır sayısını döner (0: kullanıcı yok).
    Commit çağırana aittir.
    """
    changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    cursor.execute(
        "UPDATE Users SET Password = ?, PasswordChangedAt = ? WHERE UserID = ?;",
        (hash_password(new_password), changed_at, user_id)
    )
    return cursor.rowcount


# ==========================================
# OTURUM TOKEN'I (HMAC imzalı, durumsuz)
# ==========================================

AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "").strip()
if not AUTH_SECRET_KEY:
    # Anahtar yoksa geçici anahtar üretilir: servis yeniden başlatılınca oturumlar düşer ve
    # birden fazla uvicorn worker'ı birbirinin token'ını tanımaz. Canlı ortamda .env içinde tanımlayın.
    AUTH_SECRET_KEY = secrets.token_urlsafe(48)
    print("[UYARI] AUTH_SECRET_KEY tanımlı değil; geçici anahtar üretildi. Canlı ortamda .env içine ekleyin.")

TOKEN_TTL_SECONDS = int(float(os.getenv("AUTH_TOKEN_TTL_HOURS", "12")) * 3600)


def _sign(payload_b64: str) -> str:
    return _b64e(hmac.new(AUTH_SECRET_KEY.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest())


def create_access_token(user_id: int, role: str) -> str:
    now = time.time()
    # iat: şifre değiştiğinde bundan önce verilmiş oturumları geçersiz saymak için (bkz. _authenticate)
    payload = {"uid": user_id, "role": role, "iat": now, "exp": int(now) + TOKEN_TTL_SECONDS}
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(payload_b64)}"


def decode_access_token(token: str) -> Optional[dict]:
    """İmzası geçerli ve süresi dolmamış token'ın içeriğini döner; aksi halde None."""
    try:
        payload_b64, signature = token.split(".")
    except ValueError:
        return None

    if not hmac.compare_digest(signature, _sign(payload_b64)):
        return None

    try:
        payload = json.loads(_b64d(payload_b64))
    except (ValueError, TypeError):
        return None

    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
        return None
    return payload


def _authenticate(authorization: Optional[str]) -> dict:
    """
    'Authorization: Bearer <token>' başlığını doğrular ve kullanıcının veritabanında hâlâ var olduğunu kontrol eder.
    Güncel rolü veritabanından okuyarak {'uid', 'role'} döner.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Oturum geçersiz veya süresi dolmuş. Lütfen tekrar giriş yapınız.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized

    payload = decode_access_token(authorization[7:].strip())
    if not payload:
        raise unauthorized

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT Role, PasswordChangedAt FROM Users WHERE UserID = ?;", (payload.get("uid"),))
        row = cursor.fetchone()

    if not row:
        raise unauthorized

    # Şifre bu oturum açıldıktan sonra değiştiyse oturum geçersizdir
    if row.PasswordChangedAt is not None:
        changed_at = row.PasswordChangedAt.replace(tzinfo=timezone.utc).timestamp()
        if float(payload.get("iat", 0)) < changed_at:
            raise unauthorized

    return {"uid": payload["uid"], "role": row.Role}


def require_user(authorization: Optional[str] = Header(None)) -> dict:
    """Giriş yapmış herhangi bir kullanıcı (EMPLOYEE veya ADMIN) gerektiren endpoint'ler için bağımlılık."""
    return _authenticate(authorization)


def require_admin(authorization: Optional[str] = Header(None)) -> dict:
    """Admin endpoint'leri için bağımlılık: kullanıcının veritabanında hâlâ ADMIN rolünde olduğunu kontrol eder."""
    user = _authenticate(authorization)
    if user["role"] != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yönetici (ADMIN) yetkisi gereklidir.")
    return user


# ==========================================
# KİOSK TERMİNAL ANAHTARI
# ==========================================

TERMINAL_KEY_PREFIX = "tk_"


def generate_terminal_key() -> str:
    """Kiosk terminali için yeni anahtar üretir. Yalnızca bir kez gösterilir; veritabanında hash'i saklanır."""
    return TERMINAL_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_terminal_key(key: str) -> str:
    # Anahtar yüksek entropili rastgele değer olduğu için yavaş hash (PBKDF2) gerekmez; SHA-256 ile indeksli arama yapılır
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def require_terminal(authorization: Optional[str] = Header(None)) -> dict:
    """
    Kiosk endpoint'leri için bağımlılık: 'Authorization: Bearer <terminal anahtarı>' başlığını doğrular.
    Aktif terminalin bilgilerini (konum dahil) döner. Kullanıcı oturum token'ları burada geçersizdir.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Terminal anahtarı geçersiz veya terminal devre dışı.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized

    key = authorization[7:].strip()
    if not key.startswith(TERMINAL_KEY_PREFIX):
        raise unauthorized

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.TerminalID, t.TerminalCode, t.TerminalName, l.DisplayName AS LocationName
            FROM Terminals t
            LEFT JOIN Locations l ON l.LocationID = t.LocationID
            WHERE t.TerminalKeyHash = ? AND t.IsActive = 1;
            """,
            (hash_terminal_key(key),)
        )
        row = cursor.fetchone()

    if not row:
        raise unauthorized

    return {
        "terminal_id": row.TerminalID,
        "terminal_code": row.TerminalCode,
        "terminal_name": row.TerminalName,
        "location_name": row.LocationName,
    }
