"""
Users tablosundaki düz metin şifreleri PBKDF2-SHA256 hashine dönüştürür.
Tekrar çalıştırılması güvenlidir (idempotent): zaten hashlenmiş kayıtlar atlanır.

Kullanım (proje kök dizininden, .env okunabilsin diye):
    python migrations/002_hash_passwords.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db_connection
from auth import hash_password, is_password_hashed


def migrate():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT UserID, Password FROM Users;")
        rows = cursor.fetchall()

        pending = [row for row in rows if not is_password_hashed(row.Password)]
        for row in pending:
            cursor.execute(
                "UPDATE Users SET Password = ? WHERE UserID = ?;",
                (hash_password(row.Password or ""), row.UserID)
            )
        conn.commit()

    print(f"{len(rows)} kullanıcı incelendi, {len(pending)} şifre hashlendi.")


if __name__ == "__main__":
    migrate()
