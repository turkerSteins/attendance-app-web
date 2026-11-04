# ==============================================================================
# [SERTIFIKA_MTLS_DEVRE_DISI]
# Bu dosyadaki mTLS istemci sertifikası ve cihaz güven doğrulama mekanizmaları
# geçici olarak devre dışı bırakılmış ve yorum satırına alınmıştır.
# Yeniden aktif etmek için aşağıdaki yorum satırlarını (#) kaldırabilirsiniz.
# ==============================================================================

# from typing import Optional
# from pydantic import BaseModel, Field
# from fastapi import Request
# 
# class DeviceTrustInfo(BaseModel):
#     """
#     Reverse proxy (Nginx) mTLS başlıklarından ayrıştırılan cihaz doğrulama ve güven kütüğü modeli.
#     """
#     device_trust_status: str = Field(
#         ...,
#         description="Cihaz doğrulama durumu ('VERIFIED_COMPANY_DEVICE' veya 'UNVERIFIED_PERSONAL_DEVICE')",
#         example="VERIFIED_COMPANY_DEVICE"
#     )
#     is_trusted_device: bool = Field(
#         ...,
#         description="Cihazın kurumsal/güvenilir cihaz olup olmadığı",
#         example=True
#     )
#     certificate_dn: Optional[str] = Field(
#         None,
#         description="Sertifika konu bilgisi (Distinguished Name - DN)",
#         example="CN=DEV-TEL-01_EMP-19"
#     )
#     certificate_serial: Optional[str] = Field(
#         None,
#         description="Sertifika seri numarası",
#         example="1234567890ABCDEF"
#     )
# 
# def get_device_trust_info(request: Request) -> DeviceTrustInfo:
#     """
#     Nginx reverse proxy'den gelen mTLS HTTP başlıklarını (X-Client-Verify, X-Client-Cert-DN, X-Client-Cert-Serial)
#     ayrıştıran bağımlılık fonksiyonu.
#     
#     Bu fonksiyon denetim ve cihaz kategorizasyonu amaçlıdır. Sertifika eksik veya geçersiz olsa bile
#     kesinlikle hata (401/403) fırlatmaz, isteği 'UNVERIFIED_PERSONAL_DEVICE' olarak işaretler.
#     """
#     raw_verify = request.headers.get("x-client-verify", "").strip()
#     
#     if raw_verify.upper() == "SUCCESS":
#         dn = request.headers.get("x-client-cert-dn")
#         serial = request.headers.get("x-client-cert-serial")
#         
#         # Boş dize geldiyse None olarak temizle
#         dn_clean = dn.strip() if dn and dn.strip() else None
#         serial_clean = serial.strip() if serial and serial.strip() else None
#         
#         return DeviceTrustInfo(
#             device_trust_status="VERIFIED_COMPANY_DEVICE",
#             is_trusted_device=True,
#             certificate_dn=dn_clean,
#             certificate_serial=serial_clean
#         )
#     
#     return DeviceTrustInfo(
#         device_trust_status="UNVERIFIED_PERSONAL_DEVICE",
#         is_trusted_device=False,
#         certificate_dn=None,
#         certificate_serial=None
#     )
