import re
import sys
import time
from fastapi.testclient import TestClient
from main import app
from init_db import init_db

client = TestClient(app)

def test_all_endpoints():
    print("--- 0. Database Initializing ---")
    init_db()

    print("\n--- 1. Health Check Test ---")
    res = client.get("/api/v1/health")
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200

    print("\n--- 1b. Dynamic Locations Test ---")
    res_locs = client.get("/api/v1/locations")
    print(f"Status: {res_locs.status_code}, Count: {len(res_locs.json())}")
    assert res_locs.status_code == 200
    locs = res_locs.json()
    assert len(locs) >= 3
    codes = [l["Code"] for l in locs]
    assert "OFIS" in codes
    assert "ATOLYE" in codes
    assert "SAHA" in codes

    print("\n--- 1c. Attendance Test Employee Setup ---")
    admin_token = client.post("/api/v1/auth/login", json={"EmployeeCode": "admin", "Password": "admin123"}).json()["token"]
    att_emp_code = f"ATT-{int(time.time())}"
    res = client.post(
        "/api/v1/admin/users",
        json={"FullName": "Test Saha Çalışanı", "EmployeeCode": att_emp_code, "Password": "attpass123", "Role": "EMPLOYEE"},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert res.status_code == 201
    test_user_id = res.json()["UserID"]
    res = client.post("/api/v1/auth/login", json={"EmployeeCode": att_emp_code, "Password": "attpass123"})
    assert res.json()["success"] is True
    emp_auth = {"Authorization": f"Bearer {res.json()['token']}"}

    print("\n--- 1d. Attendance Endpoints Without Token Test ---")
    assert client.get(f"/api/v1/attendance/status/{test_user_id}").status_code == 401
    assert client.get(f"/api/v1/attendance/history/{test_user_id}").status_code == 401
    assert client.post("/api/v1/attendance/check-in", json={"LocationDescription": "X"}).status_code == 401

    print("\n--- 2. Initial User Status Test ---")
    res = client.get(f"/api/v1/attendance/status/{test_user_id}", headers=emp_auth)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200

    print("\n--- 3. Check-In Test ---")
    checkin_payload = {
        "LocationDescription": "Test Şantiyesi - Ana Giriş",
        "Latitude": 41.0082,
        "Longitude": 28.9784,
        "DeviceInfo": "Test Script / Python TestClient",
        "ResolvedAddress": "Fatih / İstanbul, Sultanahmet Mah. Divan Yolu Cd."
    }
    res = client.post("/api/v1/attendance/check-in", json=checkin_payload, headers=emp_auth)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 201
    checkin_data = res.json()
    assert checkin_data["ActionType"] == "CHECK_IN"
    assert checkin_data["UserID"] == test_user_id
    assert checkin_data["ResolvedAddress"] == "Fatih / İstanbul, Sultanahmet Mah. Divan Yolu Cd."

    print("\n--- 3b. Duplicate Check-In Test (Within 10s - Idempotency Check) ---")
    res = client.post("/api/v1/attendance/check-in", json=checkin_payload, headers=emp_auth)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code in (200, 201)
    dup_checkin = res.json()
    assert dup_checkin["LogID"] == checkin_data["LogID"]
    assert dup_checkin["ActionType"] == "CHECK_IN"

    print("\n--- 4. Updated Status Test (Should be checked in) ---")
    res = client.get(f"/api/v1/attendance/status/{test_user_id}", headers=emp_auth)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["is_checked_in"] is True
    assert status_data["last_action"] == "CHECK_IN"

    print("\n--- 5. Check-Out Test ---")
    checkout_payload = {
        "LocationDescription": "Test Şantiyesi - Ana Çıkış",
        "Latitude": 41.0082,
        "Longitude": 28.9784,
        "DeviceInfo": "Test Script / Python TestClient",
        "ResolvedAddress": "Fatih / İstanbul, Sultanahmet Mah. Divan Yolu Cd."
    }
    res = client.post("/api/v1/attendance/check-out", json=checkout_payload, headers=emp_auth)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 201
    checkout_data = res.json()
    assert checkout_data["ActionType"] == "CHECK_OUT"

    print("\n--- 5b. Duplicate Check-Out Test (Within 10s - Idempotency Check) ---")
    res = client.post("/api/v1/attendance/check-out", json=checkout_payload, headers=emp_auth)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code in (200, 201)
    dup_checkout = res.json()
    assert dup_checkout["LogID"] == checkout_data["LogID"]
    assert dup_checkout["ActionType"] == "CHECK_OUT"

    print("\n--- 6. Final Status Test (Should be checked out) ---")
    res = client.get(f"/api/v1/attendance/status/{test_user_id}", headers=emp_auth)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["is_checked_in"] is False
    assert status_data["last_action"] == "CHECK_OUT"

    print("\n--- 7. History Test ---")
    res = client.get(f"/api/v1/attendance/history/{test_user_id}?limit=10", headers=emp_auth)
    print(f"Status: {res.status_code}, Count: {len(res.json())}")
    assert res.status_code == 200
    assert len(res.json()) >= 2

    # ==========================================
    # ADMIN PANEL & AUTH TESTS
    # ==========================================

    print("\n--- 8. Admin Login Test ---")
    login_payload = {
        "EmployeeCode": "admin",
        "Password": "admin123"
    }
    res = client.post("/api/v1/auth/login", json=login_payload)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    login_data = res.json()
    assert login_data["success"] is True
    assert login_data["user"]["Role"] == "ADMIN"
    assert login_data["token"]
    admin_headers = {"Authorization": f"Bearer {login_data['token']}"}

    print("\n--- 8b. Admin Endpoints Without / Invalid Token Test ---")
    assert client.get("/api/v1/admin/users").status_code == 401
    assert client.get("/api/v1/admin/reports", headers={"Authorization": "Bearer invalid.token"}).status_code == 401
    assert client.get(f"/api/v1/admin/reports/employee?employeeId={test_user_id}").status_code == 401

    print("\n--- 9. Create User Test (MSSQL) ---")
    new_emp_code = f"EMP-{int(time.time())}"
    create_user_payload = {
        "FullName": "Ahmet Yılmaz",
        "EmployeeCode": new_emp_code,
        "CardUID": f"RFID-{int(time.time())}",
        "Password": "password123",
        "Role": "EMPLOYEE"
    }
    res = client.post("/api/v1/admin/users", json=create_user_payload, headers=admin_headers)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 201
    user_data = res.json()
    assert user_data["EmployeeCode"] == new_emp_code
    assert user_data["Role"] == "EMPLOYEE"

    print("\n--- 10. Employee Login Test (By Code & Password) ---")
    emp_login_payload = {
        "EmployeeCode": new_emp_code,
        "Password": "password123"
    }
    res = client.post("/api/v1/auth/login", json=emp_login_payload)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["user"]["FullName"] == "Ahmet Yılmaz"

    print("\n--- 10a. Employee Token Cannot Access Admin API ---")
    emp_headers = {"Authorization": f"Bearer {res.json()['token']}"}
    assert client.get("/api/v1/admin/users", headers=emp_headers).status_code == 403

    print("\n--- 10a-2. Employee Cannot Read Another Employee's Records ---")
    assert client.get(f"/api/v1/attendance/history/{test_user_id}", headers=emp_headers).status_code == 403
    assert client.get(f"/api/v1/attendance/status/{test_user_id}", headers=emp_headers).status_code == 403

    print("\n--- 10b. Employee Login Test (By Full Name & Password) ---")
    emp_name_login_payload = {
        "EmployeeCode": "Ahmet Yılmaz",
        "Password": "password123"
    }
    res = client.post("/api/v1/auth/login", json=emp_name_login_payload)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    assert res.json()["success"] is True

    print("\n--- 10c. Employee Login Test (Wrong Password) ---")
    wrong_pwd_payload = {
        "EmployeeCode": new_emp_code,
        "Password": "wrongpassword"
    }
    res = client.post("/api/v1/auth/login", json=wrong_pwd_payload)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    assert res.json()["success"] is False

    # ==========================================
    # ŞİFRE DEĞİŞTİRME / BELİRLEME TESTLERİ
    # ==========================================
    emp_user_id = client.post("/api/v1/auth/login", json={"EmployeeCode": new_emp_code, "Password": "password123"}).json()["user"]["UserID"]

    print("\n--- 10d. Change Own Password: wrong current / too short / same ---")
    res = client.post("/api/v1/auth/change-password", json={"CurrentPassword": "wrong-pass", "NewPassword": "YeniSifre123"}, headers=emp_headers)
    assert res.status_code == 400, res.json()  # 401 değil: istemci oturumu kapatmamalı
    res = client.post("/api/v1/auth/change-password", json={"CurrentPassword": "password123", "NewPassword": "  kisa  "}, headers=emp_headers)
    assert res.status_code == 422
    res = client.post("/api/v1/auth/change-password", json={"CurrentPassword": "password123", "NewPassword": "password123"}, headers=emp_headers)
    assert res.status_code == 400
    assert client.post("/api/v1/auth/change-password", json={"CurrentPassword": "x", "NewPassword": "YeniSifre123"}).status_code == 401

    print("\n--- 10e. Change Own Password: success, other sessions invalidated ---")
    second_session = {"Authorization": f"Bearer {client.post('/api/v1/auth/login', json={'EmployeeCode': new_emp_code, 'Password': 'password123'}).json()['token']}"}
    res = client.post("/api/v1/auth/change-password", json={"CurrentPassword": "password123", "NewPassword": "  YeniSifre123  "}, headers=emp_headers)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    fresh_emp_headers = {"Authorization": f"Bearer {res.json()['token']}"}
    assert client.get(f"/api/v1/attendance/status/{emp_user_id}", headers=emp_headers).status_code == 401
    assert client.get(f"/api/v1/attendance/status/{emp_user_id}", headers=second_session).status_code == 401
    assert client.get(f"/api/v1/attendance/status/{emp_user_id}", headers=fresh_emp_headers).status_code == 200
    assert client.post("/api/v1/auth/login", json={"EmployeeCode": new_emp_code, "Password": "password123"}).json()["success"] is False
    assert client.post("/api/v1/auth/login", json={"EmployeeCode": new_emp_code, "Password": "YeniSifre123"}).json()["success"] is True  # kırpılmış saklandı

    print("\n--- 10f. Admin Sets User Password ---")
    assert client.post(f"/api/v1/admin/users/{emp_user_id}/password", json={"NewPassword": "AdminVerdi123"}, headers=fresh_emp_headers).status_code == 403
    res = client.post(f"/api/v1/admin/users/{emp_user_id}/password", json={"NewPassword": "AdminVerdi123"}, headers=admin_headers)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    assert client.get(f"/api/v1/attendance/status/{emp_user_id}", headers=fresh_emp_headers).status_code == 401
    res = client.post("/api/v1/auth/login", json={"EmployeeCode": new_emp_code, "Password": "AdminVerdi123"})
    assert res.json()["success"] is True
    emp_headers = {"Authorization": f"Bearer {res.json()['token']}"}  # sonraki testler için geçerli çalışan oturumu
    assert client.get(f"/api/v1/attendance/status/{emp_user_id}", headers=emp_headers).status_code == 200

    print("\n--- 10g. Admin Set Password Edge Cases ---")
    admin_user_id = login_data["user"]["UserID"]
    assert client.post(f"/api/v1/admin/users/{admin_user_id}/password", json={"NewPassword": "BaskaSifre123"}, headers=admin_headers).status_code == 400
    assert client.post("/api/v1/admin/users/999999/password", json={"NewPassword": "BaskaSifre123"}, headers=admin_headers).status_code == 404
    assert client.post(f"/api/v1/admin/users/{emp_user_id}/password", json={"NewPassword": "kisa"}, headers=admin_headers).status_code == 422
    assert client.post(
        "/api/v1/admin/users",
        json={"FullName": "Kısa Şifre", "EmployeeCode": f"SHORT-{int(time.time())}", "Password": "123", "Role": "EMPLOYEE"},
        headers=admin_headers
    ).status_code == 422
    assert client.get("/api/v1/admin/users", headers=admin_headers).status_code == 200  # admin oturumu etkilenmedi

    print("\n--- 11. List Users Test ---")
    res = client.get("/api/v1/admin/users", headers=admin_headers)
    print(f"Status: {res.status_code}, Users Count: {len(res.json())}")
    assert res.status_code == 200
    assert len(res.json()) >= 1

    print("\n--- 11. Attendance Daily Reports Test ---")
    res = client.get("/api/v1/admin/reports?filter_type=daily", headers=admin_headers)
    print(f"Status: {res.status_code}, Daily Logs Count: {len(res.json())}")
    assert res.status_code == 200

    print("\n--- 12. Attendance Weekly Reports Test ---")
    res = client.get("/api/v1/admin/reports?filter_type=weekly", headers=admin_headers)
    print(f"Status: {res.status_code}, Weekly Logs Count: {len(res.json())}")
    assert res.status_code == 200

    print("\n--- 13. Attendance Monthly Reports Test ---")
    res = client.get("/api/v1/admin/reports?filter_type=monthly", headers=admin_headers)
    print(f"Status: {res.status_code}, Monthly Logs Count: {len(res.json())}")
    assert res.status_code == 200

    print("\n--- 14. Employee Specific Attendance Report Test (Daily, Weekly, Monthly, Custom) ---")
    res = client.get(f"/api/v1/admin/reports/employee?employeeId={test_user_id}&range=weekly", headers=admin_headers)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    emp_report = res.json()
    assert "employee" in emp_report
    assert "records" in emp_report
    assert emp_report["employee"]["UserID"] == test_user_id
    assert emp_report["employee"]["total_records"] >= 2
    assert "total_work_hours" in emp_report["employee"]

    # Test String Employee Code parameter
    res_code = client.get(f"/api/v1/admin/reports/employee?employeeId={new_emp_code}&range=weekly", headers=admin_headers)
    print(f"Status string code: {res_code.status_code}, Body: {res_code.json()}")
    assert res_code.status_code == 200
    assert res_code.json()["employee"]["EmployeeCode"] == new_emp_code

    # Test Custom Date Range
    res_custom = client.get(f"/api/v1/admin/reports/employee?employeeId={test_user_id}&range=custom&start_date=2026-01-01&end_date=2026-12-31", headers=admin_headers)
    assert res_custom.status_code == 200
    assert res_custom.json()["employee"]["total_records"] >= 2

    # Test Alias Route
    res_alias = client.get(f"/api/admin/reports/employee?employeeId={test_user_id}&range=daily", headers=admin_headers)
    assert res_alias.status_code == 200

    print("\n--- 14b. Second User Without Card UID Test (filtered unique index) ---")
    res = client.post(
        "/api/v1/admin/users",
        json={"FullName": "Kartsız Çalışan", "EmployeeCode": f"NOCARD-{int(time.time())}", "Password": "nocard123", "Role": "EMPLOYEE"},
        headers=admin_headers
    )
    assert res.status_code == 201, res.json()

    # ==========================================
    # KİOSK TERMİNAL TESTLERİ
    # ==========================================
    import main as main_module
    from database import get_db_connection

    print("\n--- 16. Terminal Create Test ---")
    locs = client.get("/api/v1/admin/locations", headers=admin_headers).json()
    atolye_id = next(l["LocationID"] for l in locs if l["Code"] == "ATOLYE")
    term_code = f"KIOSK-{int(time.time())}"
    res = client.post(
        "/api/v1/admin/terminals",
        json={"TerminalCode": term_code, "TerminalName": "Test Kiosk", "LocationID": atolye_id},
        headers=admin_headers
    )
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 201
    terminal_id = res.json()["terminal"]["TerminalID"]
    terminal_key = res.json()["TerminalKey"]
    assert terminal_key.startswith("tk_")
    assert res.json()["terminal"]["HasKey"] is True
    kiosk_headers = {"Authorization": f"Bearer {terminal_key}"}

    print("\n--- 16b. Terminal Auth Separation Tests ---")
    assert client.get("/api/v1/kiosk/ping").status_code == 401
    assert client.get("/api/v1/kiosk/ping", headers={"Authorization": "Bearer tk_wrong"}).status_code == 401
    assert client.get("/api/v1/kiosk/ping", headers=admin_headers).status_code == 401  # kullanıcı token'ı kiosk'ta geçmez
    assert client.get("/api/v1/admin/users", headers=kiosk_headers).status_code == 401  # kiosk anahtarı admin'de geçmez
    assert client.get("/api/v1/admin/terminals", headers=emp_headers).status_code == 403
    assert client.post(f"/api/v1/admin/terminals", json={"TerminalCode": term_code, "TerminalName": "Dup"}, headers=admin_headers).status_code == 400

    print("\n--- 17. Kiosk Ping Test ---")
    res = client.get("/api/v1/kiosk/ping", headers=kiosk_headers)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    assert res.json()["terminal_code"] == term_code
    assert res.json()["location"] == "Atölye"

    print("\n--- 18. Kiosk Unknown Card Test ---")
    raw_card = f"04:ab:{int(time.time()) % 100:02d}:{int(time.time() * 7) % 100:02d}:{int(time.time() * 13) % 100:02d}"
    res = client.post("/api/v1/kiosk/punch", json={"CardUID": raw_card}, headers=kiosk_headers)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    assert res.json()["result"] == "UNKNOWN_CARD"
    terminals = client.get("/api/v1/admin/terminals", headers=admin_headers).json()
    this_terminal = next(t for t in terminals if t["TerminalID"] == terminal_id)
    normalized_card = raw_card.replace(":", "").upper()
    assert this_terminal["LastUnknownCardUID"] == normalized_card
    assert this_terminal["LastSeenAt"] is not None

    print("\n--- 19. Kiosk Check-In (card registered in a different format) ---")
    card_emp_code = f"CARD-{int(time.time())}"
    res = client.post(
        "/api/v1/admin/users",
        json={"FullName": "Kartlı Çalışan", "EmployeeCode": card_emp_code, "CardUID": raw_card.replace(":", " ").lower(), "Password": "card12345", "Role": "EMPLOYEE"},
        headers=admin_headers
    )
    assert res.status_code == 201
    assert res.json()["CardUID"] == normalized_card
    card_user_id = res.json()["UserID"]

    res = client.post("/api/v1/kiosk/punch", json={"CardUID": raw_card}, headers=kiosk_headers)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.json()["result"] == "CHECK_IN"
    assert res.json()["employee_name"] == "Kartlı Çalışan"
    assert res.json()["location"] == "Atölye"
    assert res.json()["warning"] is None

    print("\n--- 20. Kiosk Too Soon Test ---")
    res = client.post("/api/v1/kiosk/punch", json={"CardUID": raw_card}, headers=kiosk_headers)
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.json()["result"] == "TOO_SOON"
    assert res.json()["last_action"] == "CHECK_IN"
    assert 0 < res.json()["retry_after_seconds"] <= main_module.KIOSK_DEBOUNCE_SECONDS

    print("\n--- 21. Kiosk Check-Out Test (debounce disabled for test) ---")
    original_debounce = main_module.KIOSK_DEBOUNCE_SECONDS
    main_module.KIOSK_DEBOUNCE_SECONDS = 0
    try:
        res = client.post("/api/v1/kiosk/punch", json={"CardUID": raw_card}, headers=kiosk_headers)
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.json()["result"] == "CHECK_OUT"

        print("\n--- 22. Kiosk Stale Check-In Test (forgotten checkout) ---")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO FieldAttendanceLogs (UserID, ActionType, LocationDescription, LogDateTime) "
                "VALUES (?, 'CHECK_IN', N'Atölye', DATEADD(hour, ?, GETDATE()));",
                (card_user_id, -int(main_module.KIOSK_STALE_CHECKIN_HOURS) - 4)
            )
            # Bu eski girişi en son hareket yapmak için önceki kayıtları da daha eskiye çek
            cursor.execute(
                "UPDATE FieldAttendanceLogs SET LogDateTime = DATEADD(hour, ?, GETDATE()) "
                "WHERE UserID = ? AND TerminalID IS NOT NULL;",
                (-int(main_module.KIOSK_STALE_CHECKIN_HOURS) - 10, card_user_id)
            )
            conn.commit()
        res = client.post("/api/v1/kiosk/punch", json={"CardUID": raw_card}, headers=kiosk_headers)
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.json()["result"] == "CHECK_IN"
        assert res.json()["warning"] == "MISSING_CHECKOUT"
    finally:
        main_module.KIOSK_DEBOUNCE_SECONDS = original_debounce

    print("\n--- 23. Kiosk Records Visible In Admin Report ---")
    res = client.get(f"/api/v1/admin/reports/employee?employeeId={card_emp_code}&range=weekly", headers=admin_headers)
    assert res.status_code == 200
    assert any("Kiosk" in (r["DeviceInfo"] or "") for r in res.json()["records"])

    print("\n--- 24. Terminal Key Regenerate & Deactivate Tests ---")
    res = client.post(f"/api/v1/admin/terminals/{terminal_id}/key", headers=admin_headers)
    assert res.status_code == 200
    new_key = res.json()["TerminalKey"]
    assert new_key != terminal_key
    assert client.get("/api/v1/kiosk/ping", headers=kiosk_headers).status_code == 401  # eski anahtar geçersiz
    new_kiosk_headers = {"Authorization": f"Bearer {new_key}"}
    assert client.get("/api/v1/kiosk/ping", headers=new_kiosk_headers).status_code == 200

    res = client.patch(f"/api/v1/admin/terminals/{terminal_id}", json={"IsActive": False}, headers=admin_headers)
    assert res.status_code == 200 and res.json()["IsActive"] is False
    assert client.post("/api/v1/kiosk/punch", json={"CardUID": raw_card}, headers=new_kiosk_headers).status_code == 401
    res = client.patch(f"/api/v1/admin/terminals/{terminal_id}", json={"IsActive": True}, headers=admin_headers)
    assert client.get("/api/v1/kiosk/ping", headers=new_kiosk_headers).status_code == 200
    assert client.post(f"/api/v1/admin/terminals/999999/key", headers=admin_headers).status_code == 404

    print("\n--- 24b. Kiosk Page Download (public) ---")
    res = client.get("/kiosk/download")
    assert res.status_code == 200
    assert "attachment" in res.headers.get("content-disposition", "") and "kiosk.html" in res.headers["content-disposition"]
    assert "KIOSK_CONFIG" in res.text
    assert not re.search(r"tk_[A-Za-z0-9_-]{20,}", res.text)  # gerçek bir terminal anahtarı içermemeli

    print("\n--- 25. Kiosk CORS Preflight From file:// (Origin: null) ---")
    res = client.options(
        "/api/v1/kiosk/punch",
        headers={"Origin": "null", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"}
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") in ("null", "*")

    # =========================================================================
    # [SERTIFIKA_MTLS_DEVRE_DISI]
    # Bölüm 15 mTLS Cihaz Güven Entegrasyon Testleri geçici olarak devre dışıdır.
    # =========================================================================
    # print("\n--- 15. mTLS Device Trust Integration Tests ---")
    # mtls_user_id = 888
    # 
    # # 15a. Valid mTLS Certificate Verification Test
    # mtls_headers = {
    #     "x-client-verify": "SUCCESS",
    #     "x-client-cert-dn": "CN=DEV-TEL-01_EMP-888, OU=FieldOps, O=AcmeCorp",
    #     "x-client-cert-serial": "1234567890ABCDEF"
    # }
    # checkin_payload_mtls = {
    #     "UserID": mtls_user_id,
    #     "LocationDescription": "mTLS Güvenli Giriş Noktası",
    #     "Latitude": 41.0100,
    #     "Longitude": 28.9700,
    #     "DeviceInfo": "Company Managed Phone / Android 14"
    # }
    # res_mtls_in = client.post("/api/v1/attendance/check-in", json=checkin_payload_mtls, headers=mtls_headers)
    # print(f"Status (mTLS SUCCESS): {res_mtls_in.status_code}, Body: {res_mtls_in.json()}")
    # assert res_mtls_in.status_code == 201
    # mtls_in_data = res_mtls_in.json()
    # assert mtls_in_data["DeviceTrustStatus"] == "VERIFIED_COMPANY_DEVICE"
    # assert mtls_in_data["IsTrustedDevice"] is True
    # assert mtls_in_data["DeviceCertificateDN"] == "CN=DEV-TEL-01_EMP-888, OU=FieldOps, O=AcmeCorp"
    # assert mtls_in_data["DeviceCertificateSerial"] == "1234567890ABCDEF"
    # 
    # # 15b. Unverified / Personal Device Check-Out Test (No Headers -> Non-blocking)
    # checkout_payload_mtls = {
    #     "UserID": mtls_user_id,
    #     "LocationDescription": "Kişisel Cihaz Çıkış Noktası",
    #     "Latitude": 41.0100,
    #     "Longitude": 28.9700,
    #     "DeviceInfo": "Personal Device / iOS 17"
    # }
    # res_mtls_out = client.post("/api/v1/attendance/check-out", json=checkout_payload_mtls)
    # print(f"Status (No mTLS Headers): {res_mtls_out.status_code}, Body: {res_mtls_out.json()}")
    # assert res_mtls_out.status_code == 201
    # mtls_out_data = res_mtls_out.json()
    # assert mtls_out_data["DeviceTrustStatus"] == "UNVERIFIED_PERSONAL_DEVICE"
    # assert mtls_out_data["IsTrustedDevice"] is False
    # assert mtls_out_data["DeviceCertificateDN"] is None
    # assert mtls_out_data["DeviceCertificateSerial"] is None
    # 
    # # 15c. Failed mTLS Verification Test (x-client-verify: FAILED:... -> Non-blocking)
    # failed_mtls_headers = {
    #     "x-client-verify": "FAILED:certificate expired",
    #     "x-client-cert-dn": "CN=EXPIRED-DEVICE",
    #     "x-client-cert-serial": "000000"
    # }
    # failed_user_id = 777
    # checkin_payload_failed = {
    #     "UserID": failed_user_id,
    #     "LocationDescription": "Süresi Dolan Sertifikalı Cihaz",
    #     "Latitude": 41.0100,
    #     "Longitude": 28.9700,
    #     "DeviceInfo": "Old Managed Phone"
    # }
    # res_failed_in = client.post("/api/v1/attendance/check-in", json=checkin_payload_failed, headers=failed_mtls_headers)
    # print(f"Status (mTLS FAILED): {res_failed_in.status_code}, Body: {res_failed_in.json()}")
    # assert res_failed_in.status_code == 201
    # failed_in_data = res_failed_in.json()
    # assert failed_in_data["DeviceTrustStatus"] == "UNVERIFIED_PERSONAL_DEVICE"
    # assert failed_in_data["IsTrustedDevice"] is False
    # assert failed_in_data["DeviceCertificateDN"] is None
    # assert failed_in_data["DeviceCertificateSerial"] is None

    print("\n=== TÜM SİSTEM VEYA ADMIN YÖNETİM PANELİ TESTLERİ BAŞARIYLA GEÇTİ ===")

if __name__ == "__main__":
    test_all_endpoints()


