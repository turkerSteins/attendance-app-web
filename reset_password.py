"""
Bir kullanıcının şifresini sıfırlar (şifre ekranda görünmez, komut geçmişine yazılmaz).

Kullanım (proje kök dizininden):
    python reset_password.py admin
"""
import sys
from getpass import getpass

from database import get_db_connection
from auth import set_user_password

MIN_LENGTH = 12


def reset_password(employee_code: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT UserID, FullName, Role FROM Users WHERE EmployeeCode = ?;", (employee_code,))
        user = cursor.fetchone()
        if not user:
            print(f"HATA: '{employee_code}' kodlu kullanıcı bulunamadı.")
            sys.exit(1)

        print(f"Kullanıcı: {user.FullName} ({user.Role})")
        password = getpass("Yeni şifre: ")
        if len(password) < MIN_LENGTH:
            print(f"HATA: Şifre en az {MIN_LENGTH} karakter olmalıdır.")
            sys.exit(1)
        if password != password.strip():
            # Giriş formu şifrenin başındaki/sonundaki boşlukları kırptığı için böyle bir şifreyle giriş yapılamaz
            print("HATA: Şifre boşlukla başlayamaz veya bitemez.")
            sys.exit(1)
        if getpass("Yeni şifre (tekrar): ") != password:
            print("HATA: Şifreler eşleşmiyor.")
            sys.exit(1)

        set_user_password(cursor, user.UserID, password)
        conn.commit()
        print("Şifre güncellendi. Kullanıcının açık oturumları kapatıldı.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Kullanım: python reset_password.py <ÇalışanKodu>")
        sys.exit(1)
    reset_password(sys.argv[1].strip())
