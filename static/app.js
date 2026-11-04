// Global State
let currentUserId = null;
let currentNumericUserId = null;
let isUserCheckedIn = false;
let currentGpsCoords = null;
let currentResolvedAddress = null;
let clientIpAddress = null;
let isSubmitting = false;

let activeLoginMode = 'employee';
let currentAdminUser = null;
let activeAdminTab = 'reports';
let activeReportFilter = 'weekly';

let activeReportSubtab = 'all';
let selectedReportEmployeeId = '';
let selectedReportRange = 'weekly';

// DOM Elements - Views & Auth
const loginView = document.getElementById('loginView');
const dashboardView = document.getElementById('dashboardView');
const adminDashboardView = document.getElementById('adminDashboardView');

const loginUserIdInput = document.getElementById('loginUserIdInput');
const loginPasswordInput = document.getElementById('loginPasswordInput');
const userWelcomeText = document.getElementById('userWelcomeText');
const logoutBtn = document.getElementById('logoutBtn');

const loginTabEmpBtn = document.getElementById('loginTabEmpBtn');
const loginTabAdminBtn = document.getElementById('loginTabAdminBtn');
const loginForm = document.getElementById('loginForm');
const adminLoginForm = document.getElementById('adminLoginForm');
const adminCodeInput = document.getElementById('adminCodeInput');
const adminPasswordInput = document.getElementById('adminPasswordInput');
const adminWelcomeText = document.getElementById('adminWelcomeText');

// DOM Elements - Admin Sections & Tables
const adminReportsSection = document.getElementById('adminReportsSection');
const adminUsersSection = document.getElementById('adminUsersSection');
const adminTabReportsBtn = document.getElementById('adminTabReportsBtn');
const adminTabUsersBtn = document.getElementById('adminTabUsersBtn');
const adminReportTableBody = document.getElementById('adminReportTableBody');
const registeredUsersTableBody = document.getElementById('registeredUsersTableBody');

const statTotalLogs = document.getElementById('statTotalLogs');
const statCheckIns = document.getElementById('statCheckIns');
const statCheckOuts = document.getElementById('statCheckOuts');

// DOM Elements - User Creation Form
const newFullNameInput = document.getElementById('newFullNameInput');
const newEmployeeCodeInput = document.getElementById('newEmployeeCodeInput');
const newCardUidInput = document.getElementById('newCardUidInput');
const newPasswordInput = document.getElementById('newPasswordInput');
const newRoleSelect = document.getElementById('newRoleSelect');

// DOM Elements - Modals
const historyModal = document.getElementById('historyModal');
const openHistoryModalBtn = document.getElementById('openHistoryModalBtn');
const closeHistoryModalBtn = document.getElementById('closeHistoryModalBtn');
const closeModalFooterBtn = document.getElementById('closeModalFooterBtn');
const modalUserSubtitle = document.getElementById('modalUserSubtitle');

let pendingActionType = null;

const confirmationModal = document.getElementById('confirmationModal');
const closeConfirmModalBtn = document.getElementById('closeConfirmModalBtn');
const confirmSubmitBtn = document.getElementById('confirmSubmitBtn');
const confirmCancelBtn = document.getElementById('confirmCancelBtn');
const confirmModalTitle = document.getElementById('confirmModalTitle');
const confirmActionBadge = document.getElementById('confirmActionBadge');
const confirmTimeVal = document.getElementById('confirmTimeVal');
const confirmLocationVal = document.getElementById('confirmLocationVal');
const confirmAddressVal = document.getElementById('confirmAddressVal');
const confirmDeviceVal = document.getElementById('confirmDeviceVal');

// DOM Elements - Dashboard Cards & Info Boxes
const statusBadge = document.getElementById('statusBadge');
const lastActionVal = document.getElementById('lastActionVal');
const lastLocationVal = document.getElementById('lastLocationVal');
const lastTimeVal = document.getElementById('lastTimeVal');
const locationDescInput = document.getElementById('locationDescInput');

const deviceModelVal = document.getElementById('deviceModelVal');
const browserInfoVal = document.getElementById('browserInfoVal');
const refreshDeviceBtn = document.getElementById('refreshDeviceBtn');

const gpsCoordsVal = document.getElementById('gpsCoordsVal');
const resolvedAddressVal = document.getElementById('resolvedAddressVal');
const clientIpVal = document.getElementById('clientIpVal');
const refreshNetworkGpsBtn = document.getElementById('refreshNetworkGpsBtn');

const checkInBtn = document.getElementById('checkInBtn');
const checkOutBtn = document.getElementById('checkOutBtn');
const historyTableBody = document.getElementById('historyTableBody');
const refreshHistoryBtn = document.getElementById('refreshHistoryBtn');
const toastContainer = document.getElementById('toastContainer');

// Application Initialization
document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

function initApp() {
    // 1. Initial Device & Network & GPS & Location Detection
    updateDeviceBoxUI();
    fetchClientNetworkInfo();
    requestGpsLocation();
    fetchDynamicLocations();

    // 2. Attach Event Listeners
    if (openHistoryModalBtn) openHistoryModalBtn.addEventListener('click', openHistoryModal);
    if (closeHistoryModalBtn) closeHistoryModalBtn.addEventListener('click', closeHistoryModal);
    if (closeModalFooterBtn) closeModalFooterBtn.addEventListener('click', closeHistoryModal);
    if (historyModal) {
        historyModal.addEventListener('click', (e) => {
            if (e.target === historyModal) closeHistoryModal();
        });
    }

    if (confirmSubmitBtn) confirmSubmitBtn.addEventListener('click', executePendingAttendanceAction);
    if (confirmCancelBtn) confirmCancelBtn.addEventListener('click', closeConfirmationModal);
    if (closeConfirmModalBtn) closeConfirmModalBtn.addEventListener('click', closeConfirmationModal);
    if (confirmationModal) {
        confirmationModal.addEventListener('click', (e) => {
            if (e.target === confirmationModal) closeConfirmationModal();
        });
    }

    if (refreshDeviceBtn) {
        refreshDeviceBtn.addEventListener('click', () => {
            updateDeviceBoxUI();
            showToast('Cihaz ve tarayıcı bilgisi güncellendi.', 'info');
        });
    }

    if (refreshNetworkGpsBtn) {
        refreshNetworkGpsBtn.addEventListener('click', () => {
            fetchClientNetworkInfo();
            requestGpsLocation(true);
        });
    }

    if (logoutBtn) logoutBtn.addEventListener('click', handleLogout);
    if (refreshHistoryBtn) {
        refreshHistoryBtn.addEventListener('click', () => {
            if (currentUserId) fetchUserHistory(currentUserId);
        });
    }

    if (checkInBtn) checkInBtn.addEventListener('click', () => handleAttendanceAction('CHECK_IN'));
    if (checkOutBtn) checkOutBtn.addEventListener('click', () => handleAttendanceAction('CHECK_OUT'));

    // Admin Employee Report Event Listeners
    const empSelectEl = document.getElementById('employeeReportSelect');
    if (empSelectEl) {
        empSelectEl.addEventListener('change', onEmployeeSelectChange);
    }

    document.querySelectorAll('.emp-range-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const range = e.currentTarget.getAttribute('data-emp-range');
            setEmployeeReportRange(range);
        });
    });

    // 3. Check for active session in sessionStorage
    const savedAdmin = sessionStorage.getItem('attendance_admin_user');
    const savedUserId = sessionStorage.getItem('attendance_user_id');

    if (savedAdmin && sessionStorage.getItem('attendance_admin_token')) {
        try {
            currentAdminUser = JSON.parse(savedAdmin);
            showAdminDashboardView();
            return;
        } catch (e) {
            sessionStorage.removeItem('attendance_admin_user');
        }
    }

    if (savedUserId && sessionStorage.getItem('attendance_user_token')) {
        currentUserId = savedUserId;
        showDashboardView();
    } else {
        showLoginView();
    }
}

async function fetchDynamicLocations() {
    try {
        const response = await fetch('/api/v1/locations');
        if (!response.ok) return;
        systemLocations = await response.json();

        // SAHA location active DisplayName from Locations table
        const sahaLoc = systemLocations.find(l => l.Code === 'SAHA');
        if (sahaLoc && locationDescInput) {
            if (!locationDescInput.value || locationDescInput.value === 'Merkez Ofis - Saha 1') {
                locationDescInput.value = sahaLoc.DisplayName;
            }
        }
    } catch (err) {
        console.error("fetchDynamicLocations error:", err);
    }
}

// ----------------------------------------------------
// Device & Network Detection Logic
// ----------------------------------------------------

function detectDeviceInfo() {
    const ua = navigator.userAgent;
    let deviceType = "Masaüstü";
    let os = "Bilinmiyor";
    let browserName = "Bilinmiyor";
    let browserVersion = "";

    // Device & OS Detection
    if (/Android/i.test(ua)) {
        deviceType = "Mobil";
        os = "Android";
    } else if (/iPhone|iPad|iPod/i.test(ua)) {
        deviceType = /iPad/i.test(ua) ? "Tablet" : "Mobil";
        os = "iOS";
    } else if (/Windows/i.test(ua)) {
        deviceType = "Masaüstü";
        os = "Windows";
    } else if (/Macintosh|Mac OS X/i.test(ua)) {
        deviceType = "Masaüstü";
        os = "macOS";
    } else if (/Linux/i.test(ua)) {
        deviceType = "Masaüstü";
        os = "Linux";
    }

    // Browser Detection
    let match;
    if ((match = ua.match(/Edg\/([\d.]+)/))) {
        browserName = "Edge";
        browserVersion = match[1].split('.')[0];
    } else if ((match = ua.match(/OPR\/([\d.]+)/)) || (match = ua.match(/Opera\/([\d.]+)/))) {
        browserName = "Opera";
        browserVersion = match[1].split('.')[0];
    } else if ((match = ua.match(/Chrome\/([\d.]+)/))) {
        browserName = "Chrome";
        browserVersion = match[1].split('.')[0];
    } else if ((match = ua.match(/Firefox\/([\d.]+)/))) {
        browserName = "Firefox";
        browserVersion = match[1].split('.')[0];
    } else if ((match = ua.match(/Safari\/([\d.]+)/))) {
        browserName = "Safari";
        browserVersion = match[1].split('.')[0];
    }

    const browserFull = browserVersion ? `${browserName} v${browserVersion}` : browserName;
    const deviceFull = `${deviceType} (${os})`;

    return {
        device: deviceFull,
        browser: browserFull,
        raw: ua
    };
}

function updateDeviceBoxUI() {
    const info = detectDeviceInfo();
    if (deviceModelVal) deviceModelVal.textContent = info.device;
    if (browserInfoVal) browserInfoVal.textContent = info.browser;
}

async function fetchClientNetworkInfo() {
    if (clientIpVal) clientIpVal.textContent = "Alınıyor...";
    try {
        const response = await fetch('/api/v1/client-info');
        if (response.ok) {
            const data = await response.json();
            clientIpAddress = data.ip || '127.0.0.1';
            if (clientIpVal) clientIpVal.textContent = `${clientIpAddress}`;
        } else {
            if (clientIpVal) clientIpVal.textContent = "127.0.0.1 (Yerel)";
        }
    } catch (err) {
        console.warn("fetchClientNetworkInfo error:", err);
        if (clientIpVal) clientIpVal.textContent = "Otomatik Tespit";
    }
}

async function fetchReverseGeocode(lat, lon) {
    if (!lat || !lon) return null;
    
    if (resolvedAddressVal) resolvedAddressVal.textContent = "Adres çözümleniyor...";
    
    try {
        const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lon}&accept-language=tr`;
        const response = await fetch(url, {
            headers: {
                'Accept-Language': 'tr'
            }
        });

        if (!response.ok) throw new Error('Adres servisi yanıt vermedi.');

        const data = await response.json();
        const addr = data.address || {};

        // [İlçe / İl, Mahalle / Sokak] format
        const district = addr.city_district || addr.borough || addr.town || addr.county || addr.suburb || '';
        const city = addr.city || addr.province || addr.state || '';
        const neighbourhood = addr.suburb || addr.neighbourhood || addr.quarter || addr.residential || '';
        const road = addr.road || addr.street || addr.pedestrian || addr.footway || '';

        let mainLocation = '';
        if (district && city && district !== city) {
            mainLocation = `${district} / ${city}`;
        } else {
            mainLocation = city || district || '';
        }

        let detailLocation = '';
        if (neighbourhood && road && neighbourhood !== road) {
            detailLocation = `${neighbourhood}, ${road}`;
        } else {
            detailLocation = neighbourhood || road || '';
        }

        let formattedAddress = '';
        if (mainLocation && detailLocation) {
            formattedAddress = `${mainLocation}, ${detailLocation}`;
        } else if (mainLocation) {
            formattedAddress = mainLocation;
        } else if (detailLocation) {
            formattedAddress = detailLocation;
        } else {
            formattedAddress = data.display_name || `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
        }

        currentResolvedAddress = formattedAddress;
        if (resolvedAddressVal) resolvedAddressVal.textContent = formattedAddress;
        return formattedAddress;
    } catch (err) {
        console.warn("fetchReverseGeocode error:", err);
        currentResolvedAddress = null;
        if (resolvedAddressVal) resolvedAddressVal.textContent = "Adres alınamadı";
        return null;
    }
}

function requestGpsLocation(isManual = false) {
    if (!navigator.geolocation) {
        if (gpsCoordsVal) gpsCoordsVal.textContent = "Desteklenmiyor";
        if (resolvedAddressVal) resolvedAddressVal.textContent = "Desteklenmiyor";
        if (isManual) showToast('Tarayıcınız GPS konumunu desteklemiyor.', 'error');
        return;
    }

    if (gpsCoordsVal) gpsCoordsVal.textContent = "Alınıyor...";
    if (resolvedAddressVal) resolvedAddressVal.textContent = "Alınıyor...";

    navigator.geolocation.getCurrentPosition(
        async (position) => {
            currentGpsCoords = {
                latitude: position.coords.latitude,
                longitude: position.coords.longitude,
                accuracy: position.coords.accuracy
            };
            const acc = position.coords.accuracy ? ` (±${Math.round(position.coords.accuracy)}m)` : '';
            if (gpsCoordsVal) {
                gpsCoordsVal.textContent = `${position.coords.latitude.toFixed(4)}, ${position.coords.longitude.toFixed(4)}${acc}`;
            }

            // Ters Coğrafi Kodlama (Reverse Geocoding)
            await fetchReverseGeocode(position.coords.latitude, position.coords.longitude);

            if (isManual) showToast('GPS konumu ve açık adres başarıyla güncellendi.', 'info');
        },
        (error) => {
            console.warn("GPS Location error:", error);
            currentGpsCoords = null;
            currentResolvedAddress = null;
            if (gpsCoordsVal) gpsCoordsVal.textContent = "📍 Alınamadı (İzin yok)";
            if (resolvedAddressVal) resolvedAddressVal.textContent = "📍 Adres Alınamadı";
            if (isManual) showToast('GPS konumu alınamadı. Lütfen konum izinlerini kontrol edin.', 'error');
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
}

// ----------------------------------------------------
// Auth & Navigation
// ----------------------------------------------------

async function handleLogin() {
    const val = loginUserIdInput.value.trim();
    const password = loginPasswordInput ? loginPasswordInput.value.trim() : '';

    if (!val) {
        showToast('Lütfen Çalışan Adı veya Kodu giriniz.', 'error');
        loginUserIdInput.focus();
        return;
    }
    if (!password) {
        showToast('Lütfen şifrenizi giriniz.', 'error');
        if (loginPasswordInput) loginPasswordInput.focus();
        return;
    }

    try {
        const response = await fetch('/api/v1/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ EmployeeCode: val, Password: password })
        });

        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.message || 'Giriş başarısız. Çalışan bilgileri veya şifre hatalı.');
        }

        currentUserId = data.user.UserID;
        currentNumericUserId = data.user.UserID;
        sessionStorage.setItem('attendance_user_id', currentUserId.toString());
        sessionStorage.setItem('attendance_user_token', data.token);
        sessionStorage.setItem('attendance_user_data', JSON.stringify(data.user));

        showToast(`Hoş geldiniz, ${data.user.FullName}`, 'success');
        showDashboardView();
    } catch (err) {
        console.error("handleLogin error:", err);
        showToast(`Giriş Hatası: ${err.message}`, 'error');
    }
}

function handleLogout() {
    sessionStorage.removeItem('attendance_user_id');
    sessionStorage.removeItem('attendance_user_data');
    sessionStorage.removeItem('attendance_user_token');
    sessionStorage.removeItem('attendance_admin_user');
    sessionStorage.removeItem('attendance_admin_token');
    currentUserId = null;
    currentNumericUserId = null;
    currentAdminUser = null;
    isUserCheckedIn = false;
    hideTerminalKey();
    closePasswordModal();

    if (loginUserIdInput) loginUserIdInput.value = '';
    if (loginPasswordInput) loginPasswordInput.value = '';
    if (adminCodeInput) adminCodeInput.value = '';
    if (adminPasswordInput) adminPasswordInput.value = '';

    // Eski kullanıcıya ait tüm arayüz verilerini sıfırla
    if (userWelcomeText) userWelcomeText.textContent = 'Hoş geldiniz';
    if (lastActionVal) lastActionVal.textContent = '-';
    if (lastLocationVal) lastLocationVal.textContent = '-';
    if (lastTimeVal) lastTimeVal.textContent = '-';
    if (historyTableBody) historyTableBody.innerHTML = `<tr><td colspan="6" class="text-center py-4">Kayıtlar yükleniyor...</td></tr>`;
    if (statusBadge) {
        statusBadge.className = "status-badge status-offline";
        statusBadge.innerHTML = `<i class="fa-solid fa-circle-dot"></i> Yükleniyor...`;
    }

    showToast('Oturum kapatıldı.', 'info');
    showLoginView();
}

function showLoginView() {
    if (dashboardView) {
        dashboardView.classList.remove('active-view');
        dashboardView.classList.add('hidden-view');
    }
    if (adminDashboardView) {
        adminDashboardView.classList.remove('active-view');
        adminDashboardView.classList.add('hidden-view');
    }
    if (loginView) {
        loginView.classList.remove('hidden-view');
        loginView.classList.add('active-view');
    }
}

function showDashboardView() {
    // Yeni giriş yapan çalışan için arayüz alanlarını temizle
    if (lastActionVal) lastActionVal.textContent = '-';
    if (lastLocationVal) lastLocationVal.textContent = '-';
    if (lastTimeVal) lastTimeVal.textContent = '-';
    if (historyTableBody) historyTableBody.innerHTML = `<tr><td colspan="6" class="text-center py-4">Kayıtlar yükleniyor...</td></tr>`;

    const savedData = sessionStorage.getItem('attendance_user_data');
    if (savedData) {
        try {
            const u = JSON.parse(savedData);
            if (userWelcomeText) userWelcomeText.textContent = `Hoş geldiniz, ${u.FullName}`;
            if (modalUserSubtitle) modalUserSubtitle.textContent = `Çalışan: ${u.FullName} (Kod: ${u.EmployeeCode})`;
        } catch (e) {}
    } else {
        if (userWelcomeText) userWelcomeText.textContent = 'Hoş geldiniz';
        if (modalUserSubtitle) modalUserSubtitle.textContent = 'Mesai Geçmişi';
    }

    if (loginView) {
        loginView.classList.remove('active-view');
        loginView.classList.add('hidden-view');
    }
    if (adminDashboardView) {
        adminDashboardView.classList.remove('active-view');
        adminDashboardView.classList.add('hidden-view');
    }
    if (dashboardView) {
        dashboardView.classList.remove('hidden-view');
        dashboardView.classList.add('active-view');
    }

    // Yalnızca aktif çalışanın verilerini yükle
    if (currentUserId) {
        loadUserData(currentUserId);
    }
}

// ----------------------------------------------------
// Admin Navigation & Action Logic
// ----------------------------------------------------

function switchLoginMode(mode) {
    activeLoginMode = mode;
    if (mode === 'employee') {
        if (loginTabEmpBtn) loginTabEmpBtn.classList.add('active');
        if (loginTabAdminBtn) loginTabAdminBtn.classList.remove('active');
        if (loginForm) loginForm.classList.remove('hidden-form');
        if (adminLoginForm) adminLoginForm.classList.add('hidden-form');
    } else {
        if (loginTabAdminBtn) loginTabAdminBtn.classList.add('active');
        if (loginTabEmpBtn) loginTabEmpBtn.classList.remove('active');
        if (adminLoginForm) adminLoginForm.classList.remove('hidden-form');
        if (loginForm) loginForm.classList.add('hidden-form');
        if (adminCodeInput) adminCodeInput.focus();
    }
}

async function handleAdminLogin() {
    const code = adminCodeInput.value.trim();
    const password = adminPasswordInput.value.trim();
    
    if (!code || !password) {
        showToast('Lütfen yönetici kodunu ve şifrenizi giriniz.', 'error');
        return;
    }

    try {
        const response = await fetch('/api/v1/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ EmployeeCode: code, Password: password })
        });

        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.message || 'Giriş başarısız.');
        }

        if (data.user.Role !== 'ADMIN') {
            showToast('Bu hesap Yönetici (ADMIN) yetkisine sahip değil.', 'error');
            return;
        }

        currentAdminUser = data.user;
        sessionStorage.setItem('attendance_admin_user', JSON.stringify(currentAdminUser));
        sessionStorage.setItem('attendance_admin_token', data.token);
        showToast(`Hoş geldiniz, ${data.user.FullName}`, 'success');
        showAdminDashboardView();
    } catch (err) {
        console.error("handleAdminLogin error:", err);
        showToast(`Giriş Hatası: ${err.message}`, 'error');
    }
}

// Korumalı API çağrıları: oturum token'ını ekler, yetki hatasında oturumu kapatır
async function authFetch(tokenKey, url, options = {}) {
    const token = sessionStorage.getItem(tokenKey);
    const headers = { ...(options.headers || {}), 'Authorization': `Bearer ${token}` };
    const response = await fetch(url, { ...options, headers });

    if (response.status === 401 || response.status === 403) {
        handleLogout();
        showToast('Oturumunuz sona erdi. Lütfen tekrar giriş yapınız.', 'error');
        throw new Error('Yetkisiz erişim.');
    }
    return response;
}

const adminFetch = (url, options) => authFetch('attendance_admin_token', url, options);
const userFetch = (url, options) => authFetch('attendance_user_token', url, options);

function showAdminDashboardView() {
    if (currentAdminUser && adminWelcomeText) {
        adminWelcomeText.textContent = `Hoş geldiniz, ${currentAdminUser.FullName} (${currentAdminUser.EmployeeCode})`;
    }

    if (loginView) {
        loginView.classList.remove('active-view');
        loginView.classList.add('hidden-view');
    }
    if (dashboardView) {
        dashboardView.classList.remove('active-view');
        dashboardView.classList.add('hidden-view');
    }
    if (adminDashboardView) {
        adminDashboardView.classList.remove('hidden-view');
        adminDashboardView.classList.add('active-view');
    }

    // Load both employee-specific report & general company reports
    populateEmployeeDropdown();
    fetchAttendanceReports(activeReportFilter);
    fetchRegisteredUsers();
}

async function populateEmployeeDropdown() {
    const selectEl = document.getElementById('employeeReportSelect');
    if (!selectEl) return;

    try {
        const response = await adminFetch('/api/v1/admin/users');
        if (!response.ok) return;

        const users = await response.json();
        if (!users || users.length === 0) {
            selectEl.innerHTML = '<option value="">Sistemde Kayıtlı Çalışan Bulunmuyor</option>';
            return;
        }

        // Auto-select first employee if none selected yet
        if (!selectedReportEmployeeId && users.length > 0) {
            const empUser = users.find(u => u.Role === 'EMPLOYEE') || users[0];
            selectedReportEmployeeId = empUser.EmployeeCode || empUser.UserID;
        }

        let optionsHtml = '<option value="">-- Lütfen Çalışan Seçiniz --</option>';
        users.forEach(user => {
            const val = user.EmployeeCode || user.UserID;
            const isSel = (String(val) === String(selectedReportEmployeeId));
            optionsHtml += `<option value="${escapeHtml(val)}" ${isSel ? 'selected' : ''}>${escapeHtml(user.FullName)} (Kodu: ${escapeHtml(user.EmployeeCode || user.UserID)})</option>`;
        });

        selectEl.innerHTML = optionsHtml;
        if (selectedReportEmployeeId) {
            selectEl.value = selectedReportEmployeeId;
            fetchEmployeeAttendanceReport();
        }
    } catch (err) {
        console.error("populateEmployeeDropdown error:", err);
    }
}

function onEmployeeSelectChange() {
    const selectEl = document.getElementById('employeeReportSelect');
    if (!selectEl) return;
    selectedReportEmployeeId = selectEl.value.trim();
    fetchEmployeeAttendanceReport();
}

function setEmployeeReportRange(rangeType) {
    selectedReportRange = rangeType;
    const rangeBtns = document.querySelectorAll('.emp-range-btn');
    rangeBtns.forEach(btn => {
        if (btn.getAttribute('data-emp-range') === rangeType) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    const customBox = document.getElementById('customDateRangeBox');
    if (rangeType === 'custom') {
        if (customBox) customBox.classList.remove('hidden-view');
    } else {
        if (customBox) customBox.classList.add('hidden-view');
        fetchEmployeeAttendanceReport();
    }
}

function applyCustomDateFilter() {
    if (selectedReportRange !== 'custom') {
        selectedReportRange = 'custom';
    }
    fetchEmployeeAttendanceReport();
}

async function fetchEmployeeAttendanceReport() {
    const tableBody = document.getElementById('empReportTableBody');
    const sumName = document.getElementById('empSummaryName');
    const sumCode = document.getElementById('empSummaryCode');
    const sumRecords = document.getElementById('empSummaryRecords');
    const sumHours = document.getElementById('empSummaryWorkHours');

    if (!selectedReportEmployeeId) {
        if (sumName) sumName.textContent = 'Çalışan Seçilmedi';
        if (sumCode) sumCode.textContent = 'Lütfen yukarıdaki menüden çalışan seçiniz';
        if (sumRecords) sumRecords.textContent = '0 Kayıt';
        if (sumHours) sumHours.textContent = '0.0 Saat';
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="4" class="text-center py-4 text-muted">Lütfen raporlarını görüntülemek için yukarıdan bir çalışan seçiniz.</td></tr>`;
        }
        return;
    }

    let url = `/api/v1/admin/reports/employee?employeeId=${encodeURIComponent(selectedReportEmployeeId)}&range=${selectedReportRange}`;

    if (selectedReportRange === 'custom') {
        const startVal = document.getElementById('empReportStartDate')?.value;
        const endVal = document.getElementById('empReportEndDate')?.value;

        if (startVal) url += `&start_date=${encodeURIComponent(startVal)}`;
        if (endVal) url += `&end_date=${encodeURIComponent(endVal)}`;
    }

    try {
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="4" class="text-center py-4"><i class="fa-solid fa-spinner fa-spin"></i> Mesai raporu çekiliyor...</td></tr>`;
        }

        const response = await adminFetch(url);
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || 'Rapor verisi alınamadı.');
        }

        const data = await response.json();
        renderEmployeeReportUI(data);

    } catch (err) {
        console.error("fetchEmployeeAttendanceReport error:", err);
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="4" class="text-center text-danger py-4">Raporlar yüklenemedi: ${escapeHtml(err.message)}</td></tr>`;
        }
        showToast(`Rapor Hatası: ${err.message}`, 'error');
    }
}

function renderEmployeeReportUI(data) {
    const tableBody = document.getElementById('empReportTableBody');
    const sumName = document.getElementById('empSummaryName');
    const sumCode = document.getElementById('empSummaryCode');
    const sumRecords = document.getElementById('empSummaryRecords');
    const sumHours = document.getElementById('empSummaryWorkHours');

    if (data.employee) {
        if (sumName) sumName.textContent = data.employee.FullName;
        if (sumCode) sumCode.textContent = `Çalışan Kodu: ${data.employee.EmployeeCode} (UserID: #${data.employee.UserID})`;
        if (sumRecords) sumRecords.textContent = `${data.employee.total_records} Kayıt`;
        if (sumHours) sumHours.textContent = `${data.employee.total_work_hours} Saat`;
    }

    if (!data.records || data.records.length === 0) {
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="4" class="text-center py-4 text-muted">Seçilen tarih aralığında çalışan için mesai kaydı bulunamadı.</td></tr>`;
        }
        return;
    }

    let rowsHtml = '';
    data.records.forEach(item => {
        const isCheckIn = item.ActionType === 'CHECK_IN';
        const badgeClass = isCheckIn ? 'badge-checkin' : 'badge-checkout';
        const actionLabel = isCheckIn ? 'GİRİŞ (CHECK-IN)' : 'ÇIKIŞ (CHECK-OUT)';

        let deviceShort = item.DeviceInfo || '-';
        if (deviceShort.length > 35) {
            deviceShort = deviceShort.substring(0, 35) + '...';
        }

        rowsHtml += `
            <tr>
                <td><strong>${formatDate(item.LogDateTime)}</strong></td>
                <td><span class="badge-tag ${badgeClass}">${actionLabel}</span></td>
                <td>
                    <strong>${escapeHtml(item.LocationDescription)}</strong><br>
                    <small class="text-muted"><i class="fa-solid fa-location-dot"></i> ${escapeHtml(item.ResolvedAddress || '-')}</small>
                </td>
                <td>
                    <small title="${escapeHtml(item.DeviceInfo)}"><i class="fa-solid fa-desktop"></i> ${escapeHtml(deviceShort)}</small>
                </td>
            </tr>
        `;
    });

    if (tableBody) {
        tableBody.innerHTML = rowsHtml;
    }
}

function switchToEmployeeView() {
    if (adminDashboardView) {
        adminDashboardView.classList.remove('active-view');
        adminDashboardView.classList.add('hidden-view');
    }
    if (dashboardView) {
        dashboardView.classList.remove('hidden-view');
        dashboardView.classList.add('active-view');
    }
}

const ADMIN_TABS = {
    reports: {
        btn: 'adminTabReportsBtn',
        section: 'adminReportsSection',
        onShow: () => { populateEmployeeDropdown(); fetchAttendanceReports(activeReportFilter); }
    },
    users: {
        btn: 'adminTabUsersBtn',
        section: 'adminUsersSection',
        onShow: () => fetchRegisteredUsers()
    },
    terminals: {
        btn: 'adminTabTerminalsBtn',
        section: 'adminTerminalsSection',
        onShow: () => { populateTerminalLocationSelect(); fetchTerminals(); }
    }
};

function switchAdminTab(tabName) {
    if (!ADMIN_TABS[tabName]) return;
    activeAdminTab = tabName;

    Object.entries(ADMIN_TABS).forEach(([name, tab]) => {
        const isActive = name === tabName;
        const btn = document.getElementById(tab.btn);
        const section = document.getElementById(tab.section);
        if (btn) btn.classList.toggle('active', isActive);
        if (section) section.classList.toggle('hidden-view', !isActive);
    });

    ADMIN_TABS[tabName].onShow();
}

function filterReports(filterType) {
    activeReportFilter = filterType;
    const filterBtns = document.querySelectorAll('.filter-tab-btn');
    filterBtns.forEach(btn => {
        if (btn.getAttribute('data-filter') === filterType) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    fetchAttendanceReports(filterType);
}

async function fetchAttendanceReports(filterType = 'weekly') {
    try {
        adminReportTableBody.innerHTML = `<tr><td colspan="6" class="text-center py-4"><i class="fa-solid fa-spinner fa-spin"></i> MSSQL verileri çekiliyor (${filterType})...</td></tr>`;

        const response = await adminFetch(`/api/v1/admin/reports?filter_type=${filterType}`);
        if (!response.ok) throw new Error('Rapor verisi alınamadı.');

        const reports = await response.json();
        renderAdminReportTable(reports);
    } catch (err) {
        console.error("fetchAttendanceReports error:", err);
        adminReportTableBody.innerHTML = `<tr><td colspan="6" class="text-center text-danger py-4">Raporlar yüklenemedi.</td></tr>`;
        showToast('Mesai raporları alınırken hata oluştu.', 'error');
    }
}

function renderAdminReportTable(list) {
    if (!list || list.length === 0) {
        adminReportTableBody.innerHTML = `<tr><td colspan="6" class="text-center py-4">Seçilen filtre için mesai kaydı bulunamadı.</td></tr>`;
        if (statTotalLogs) statTotalLogs.textContent = '0';
        if (statCheckIns) statCheckIns.textContent = '0';
        if (statCheckOuts) statCheckOuts.textContent = '0';
        return;
    }

    let checkInsCount = 0;
    let checkOutsCount = 0;
    let rowsHtml = '';

    list.forEach(item => {
        const isCheckIn = item.ActionType === 'CHECK_IN';
        if (isCheckIn) checkInsCount++; else checkOutsCount++;

        const badgeClass = isCheckIn ? 'badge-checkin' : 'badge-checkout';
        const actionLabel = isCheckIn ? 'GİRİŞ (CHECK-IN)' : 'ÇIKIŞ (CHECK-OUT)';
        
        let deviceShort = item.DeviceInfo || '-';
        if (deviceShort.length > 30) {
            deviceShort = deviceShort.substring(0, 30) + '...';
        }

        rowsHtml += `
            <tr>
                <td><strong>${escapeHtml(item.EmployeeName)}</strong> <br><small class="text-muted">Kodu: ${escapeHtml(item.EmployeeCode)}</small></td>
                <td><span class="badge-tag ${badgeClass}">${actionLabel}</span></td>
                <td>${formatDate(item.LogDateTime)}</td>
                <td><strong>${escapeHtml(item.LocationDescription)}</strong></td>
                <td><small class="text-muted">${escapeHtml(item.ResolvedAddress || '-')}</small></td>
                <td><small title="${escapeHtml(item.DeviceInfo)}">${escapeHtml(deviceShort)}</small></td>
            </tr>
        `;
    });

    adminReportTableBody.innerHTML = rowsHtml;
    if (statTotalLogs) statTotalLogs.textContent = list.length.toString();
    if (statCheckIns) statCheckIns.textContent = checkInsCount.toString();
    if (statCheckOuts) statCheckOuts.textContent = checkOutsCount.toString();
}

async function handleCreateUser() {
    const fullName = newFullNameInput.value.trim();
    const employeeCode = newEmployeeCodeInput.value.trim();
    const cardUid = newCardUidInput.value.trim();
    const password = newPasswordInput.value.trim();
    const role = newRoleSelect.value;

    if (!fullName || !employeeCode || !password) {
        showToast('Lütfen zorunlu alanları (Ad Soyad, Kod, Şifre) doldurunuz.', 'error');
        return;
    }

    const payload = {
        FullName: fullName,
        EmployeeCode: employeeCode,
        CardUID: cardUid || null,
        Password: password,
        Role: role
    };

    const submitBtn = document.getElementById('createUserSubmitBtn');
    const originalText = submitBtn.innerHTML;

    try {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Kaydediliyor...`;

        const response = await adminFetch('/api/v1/admin/users', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errData = await response.json();
            throw new Error(apiErrorMessage(errData, 'Kullanıcı kaydı oluşturulamadı.'));
        }

        const createdUser = await response.json();
        showToast(`Kullanıcı '${createdUser.FullName}' MSSQL veritabanına başarıyla kaydedildi.`, 'success');

        // Formu temizle
        newFullNameInput.value = '';
        newEmployeeCodeInput.value = '';
        newCardUidInput.value = '';
        newPasswordInput.value = '';

        // Tabloyu güncelle
        fetchRegisteredUsers();
    } catch (err) {
        console.error("handleCreateUser error:", err);
        showToast(`Hata: ${err.message}`, 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
    }
}

async function fetchRegisteredUsers() {
    try {
        registeredUsersTableBody.innerHTML = `<tr><td colspan="5" class="text-center py-4"><i class="fa-solid fa-spinner fa-spin"></i> Kullanıcılar yükleniyor...</td></tr>`;

        const response = await adminFetch('/api/v1/admin/users');
        if (!response.ok) throw new Error('Kullanıcı listesi alınamadı.');

        registeredUsersCache = await response.json();
        renderRegisteredUsersTable(registeredUsersCache);
    } catch (err) {
        console.error("fetchRegisteredUsers error:", err);
        registeredUsersTableBody.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-4">Kullanıcılar yüklenemedi.</td></tr>`;
    }
}

function renderRegisteredUsersTable(list) {
    if (!list || list.length === 0) {
        registeredUsersTableBody.innerHTML = `<tr><td colspan="5" class="text-center py-4">Henüz kayıtlı kullanıcı bulunmuyor.</td></tr>`;
        return;
    }

    let rowsHtml = '';
    list.forEach(user => {
        const roleBadge = user.Role === 'ADMIN' 
            ? '<span class="badge-tag badge-checkout">ADMIN</span>' 
            : '<span class="badge-tag badge-checkin">EMPLOYEE</span>';

        rowsHtml += `
            <tr>
                <td><strong>${escapeHtml(user.EmployeeCode)}</strong></td>
                <td>${escapeHtml(user.FullName)}</td>
                <td>${roleBadge}</td>
                <td><small>${escapeHtml(user.CardUID || '-')}</small></td>
                <td>
                    <button type="button" class="btn btn-outline-emerald btn-sm" onclick="openPasswordModal('admin', ${Number(user.UserID)})">
                        <i class="fa-solid fa-key"></i> Şifre Belirle
                    </button>
                </td>
            </tr>
        `;
    });

    registeredUsersTableBody.innerHTML = rowsHtml;
}

// ----------------------------------------------------
// Admin: Kiosk Terminalleri
// ----------------------------------------------------

let terminalsCache = [];
let lastTerminalConfigText = '';

async function populateTerminalLocationSelect() {
    const selectEl = document.getElementById('newTerminalLocationSelect');
    if (!selectEl) return;

    try {
        const response = await adminFetch('/api/v1/admin/locations');
        if (!response.ok) throw new Error('Konumlar alınamadı.');

        const locations = await response.json();
        const previous = selectEl.value;
        selectEl.innerHTML = '<option value="">-- Konum Seçiniz --</option>' + locations
            .map(l => `<option value="${l.LocationID}">${escapeHtml(l.DisplayName)}</option>`)
            .join('');
        if (previous) selectEl.value = previous;
    } catch (err) {
        console.error("populateTerminalLocationSelect error:", err);
        selectEl.innerHTML = '<option value="">Konumlar yüklenemedi</option>';
    }
}

async function fetchTerminals() {
    const tableBody = document.getElementById('terminalsTableBody');
    if (!tableBody) return;

    try {
        tableBody.innerHTML = `<tr><td colspan="5" class="text-center py-4"><i class="fa-solid fa-spinner fa-spin"></i> Terminaller yükleniyor...</td></tr>`;

        const response = await adminFetch('/api/v1/admin/terminals');
        if (!response.ok) throw new Error('Terminal listesi alınamadı.');

        terminalsCache = await response.json();
        renderTerminalsTable(terminalsCache);
    } catch (err) {
        console.error("fetchTerminals error:", err);
        tableBody.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-4">Terminaller yüklenemedi.</td></tr>`;
    }
}

function renderTerminalsTable(list) {
    const tableBody = document.getElementById('terminalsTableBody');
    if (!tableBody) return;

    if (!list || list.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="5" class="text-center py-4">Henüz kayıtlı terminal bulunmuyor.</td></tr>`;
        return;
    }

    tableBody.innerHTML = list.map(t => {
        const statusBadgeHtml = t.IsActive
            ? '<span class="badge-tag badge-checkin">AKTİF</span>'
            : '<span class="badge-tag badge-checkout">DEVRE DIŞI</span>';

        const lastSeenHtml = t.LastSeenAt
            ? `${formatDate(t.LastSeenAt)}<br><small class="text-muted">${escapeHtml(t.LastSeenIP || '')}</small>`
            : '<small class="text-muted">Hiç bağlanmadı</small>';

        const unknownCardHtml = t.LastUnknownCardUID
            ? `<span class="terminal-uid">${escapeHtml(t.LastUnknownCardUID)}</span><br><small class="text-muted">${formatDate(t.LastUnknownCardAt)}</small>`
            : '-';

        const toggleBtnHtml = t.IsActive
            ? `<button type="button" class="btn btn-secondary btn-sm" onclick="setTerminalActive(${t.TerminalID}, false)" title="Anahtarı kabul edilmez">
                   <i class="fa-solid fa-ban"></i> Devre Dışı Bırak
               </button>`
            : `<button type="button" class="btn btn-outline-emerald btn-sm" onclick="setTerminalActive(${t.TerminalID}, true)">
                   <i class="fa-solid fa-circle-check"></i> Etkinleştir
               </button>`;

        return `
            <tr>
                <td>
                    <strong>${escapeHtml(t.TerminalName)}</strong><br>
                    <small class="text-muted">${escapeHtml(t.TerminalCode)} · ${escapeHtml(t.LocationName || 'Konum yok')}</small>
                </td>
                <td>${statusBadgeHtml}</td>
                <td>${lastSeenHtml}</td>
                <td>${unknownCardHtml}</td>
                <td>
                    <div class="terminal-actions-cell">
                        <button type="button" class="btn btn-outline-emerald btn-sm" onclick="regenerateTerminalKey(${t.TerminalID})" title="Eski anahtar hemen geçersiz olur">
                            <i class="fa-solid fa-key"></i> Yeni Anahtar
                        </button>
                        ${toggleBtnHtml}
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

async function handleCreateTerminal() {
    const codeInput = document.getElementById('newTerminalCodeInput');
    const nameInput = document.getElementById('newTerminalNameInput');
    const locationSelect = document.getElementById('newTerminalLocationSelect');
    const submitBtn = document.getElementById('createTerminalSubmitBtn');

    const terminalCode = codeInput.value.trim();
    const terminalName = nameInput.value.trim();
    const locationId = locationSelect.value ? parseInt(locationSelect.value, 10) : null;

    if (!terminalCode || !terminalName || !locationId) {
        showToast('Lütfen terminal kodu, adı ve konumunu giriniz.', 'error');
        return;
    }

    const originalText = submitBtn.innerHTML;
    try {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Oluşturuluyor...`;

        const response = await adminFetch('/api/v1/admin/terminals', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ TerminalCode: terminalCode, TerminalName: terminalName, LocationID: locationId })
        });

        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || 'Terminal oluşturulamadı.');
        }

        const data = await response.json();
        codeInput.value = '';
        nameInput.value = '';
        showTerminalKey(data.terminal, data.TerminalKey);
        showToast(`Terminal '${data.terminal.TerminalName}' oluşturuldu.`, 'success');
        fetchTerminals();
    } catch (err) {
        console.error("handleCreateTerminal error:", err);
        showToast(`Hata: ${err.message}`, 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
    }
}

async function regenerateTerminalKey(terminalId) {
    const terminal = terminalsCache.find(t => t.TerminalID === terminalId);
    const label = terminal ? `${terminal.TerminalName} (${terminal.TerminalCode})` : `#${terminalId}`;
    if (!confirm(`${label} için yeni anahtar üretilsin mi?\n\nEski anahtar HEMEN geçersiz olur; kioskun config.js dosyası yeni anahtarla güncellenene kadar kart okutma çalışmaz.`)) {
        return;
    }

    try {
        const response = await adminFetch(`/api/v1/admin/terminals/${terminalId}/key`, { method: 'POST' });
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || 'Anahtar üretilemedi.');
        }

        const data = await response.json();
        showTerminalKey(data.terminal, data.TerminalKey);
        showToast('Yeni anahtar üretildi. Kiosk yapılandırmasını güncelleyin.', 'success');
        fetchTerminals();
    } catch (err) {
        console.error("regenerateTerminalKey error:", err);
        showToast(`Hata: ${err.message}`, 'error');
    }
}

async function setTerminalActive(terminalId, isActive) {
    if (!isActive) {
        const terminal = terminalsCache.find(t => t.TerminalID === terminalId);
        const label = terminal ? `${terminal.TerminalName} (${terminal.TerminalCode})` : `#${terminalId}`;
        if (!confirm(`${label} devre dışı bırakılsın mı?\n\nBu kiosktan kart okutma hemen durur.`)) return;
    }

    try {
        const response = await adminFetch(`/api/v1/admin/terminals/${terminalId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ IsActive: isActive })
        });
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || 'Terminal güncellenemedi.');
        }

        showToast(isActive ? 'Terminal etkinleştirildi.' : 'Terminal devre dışı bırakıldı.', 'success');
        fetchTerminals();
    } catch (err) {
        console.error("setTerminalActive error:", err);
        showToast(`Hata: ${err.message}`, 'error');
    }
}

function showTerminalKey(terminal, terminalKey) {
    const box = document.getElementById('terminalKeyBox');
    const title = document.getElementById('terminalKeyTitle');
    const snippet = document.getElementById('terminalConfigSnippet');
    if (!box || !snippet) return;

    // Kiosk, yönetim panelinin açıldığı adresle aynı sunucuya bağlanır
    lastTerminalConfigText =
        `window.KIOSK_CONFIG = {\n` +
        `    apiUrl: ${JSON.stringify(window.location.origin)},\n` +
        `    terminalKey: ${JSON.stringify(terminalKey)}\n` +
        `};\n`;

    if (title) title.textContent = `${terminal.TerminalName} (${terminal.TerminalCode}) için config.js`;
    snippet.textContent = lastTerminalConfigText;
    box.classList.remove('hidden-view');
    box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideTerminalKey() {
    const box = document.getElementById('terminalKeyBox');
    const snippet = document.getElementById('terminalConfigSnippet');
    if (snippet) snippet.textContent = '';
    if (box) box.classList.add('hidden-view');
    lastTerminalConfigText = '';
}

function downloadTerminalConfig() {
    if (!lastTerminalConfigText) return;

    // Dosya adı "config.js" olmalı: kiosk.html yalnızca bu adı yükler
    const blob = new Blob([lastTerminalConfigText], { type: 'text/javascript' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'config.js';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

async function copyTerminalConfig() {
    try {
        await navigator.clipboard.writeText(lastTerminalConfigText);
        showToast('config.js içeriği panoya kopyalandı.', 'success');
    } catch (err) {
        // Pano erişimi yalnızca HTTPS/localhost'ta çalışır; metin tıklanınca tamamen seçilir
        showToast('Otomatik kopyalanamadı. Metni seçip Ctrl+C ile kopyalayın.', 'info');
    }
}

// ----------------------------------------------------
// Şifre Değiştirme (kendi şifresi) / Şifre Belirleme (admin)
// ----------------------------------------------------

const PASSWORD_MIN_LENGTH = 8;  // schemas.PASSWORD_MIN_LENGTH ile aynı

let registeredUsersCache = [];
let passwordModalMode = null;      // 'self' | 'admin'
let passwordModalTargetId = null;

// FastAPI doğrulama hataları (422) 'detail' alanında liste döner; okunabilir mesaja çevir
function apiErrorMessage(errData, fallback) {
    const detail = errData && errData.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length) {
        return detail.map(d => String(d.msg || '').replace(/^Value error, /, '')).filter(Boolean).join(' ') || fallback;
    }
    return fallback;
}

function openPasswordModal(mode, userId) {
    const modal = document.getElementById('passwordModal');
    if (!modal) return;

    // Admin kendi satırında "Şifre Belirle"ye basarsa mevcut şifresini doğrulayan akışa yönlendir
    if (mode === 'admin' && currentAdminUser && userId === currentAdminUser.UserID) {
        mode = 'self';
    }

    passwordModalMode = mode;
    passwordModalTargetId = mode === 'admin' ? userId : null;

    const isSelf = mode === 'self';
    const target = registeredUsersCache.find(u => u.UserID === userId);

    document.getElementById('passwordModalTitle').textContent = isSelf ? 'Şifremi Değiştir' : 'Şifre Belirle';
    document.getElementById('passwordModalSubtitle').textContent = isSelf
        ? ''
        : (target ? `${target.FullName} (${target.EmployeeCode})` : `Kullanıcı #${userId}`);
    document.getElementById('passwordModalHint').textContent = isSelf
        ? `Yeni şifre en az ${PASSWORD_MIN_LENGTH} karakter olmalıdır. Diğer cihazlardaki oturumlarınız kapatılır.`
        : `Yeni şifre en az ${PASSWORD_MIN_LENGTH} karakter olmalıdır. Kullanıcının açık oturumları kapatılır; yeni şifreyi kendisine iletiniz.`;

    document.getElementById('currentPasswordGroup').classList.toggle('hidden-form', !isSelf);
    document.getElementById('currentPasswordInput').required = isSelf;
    document.getElementById('passwordForm').reset();

    modal.classList.remove('hidden-modal');
    document.getElementById(isSelf ? 'currentPasswordInput' : 'newPasswordModalInput').focus();
}

function closePasswordModal() {
    const modal = document.getElementById('passwordModal');
    const form = document.getElementById('passwordForm');
    if (form) form.reset();
    if (modal) modal.classList.add('hidden-modal');
    passwordModalMode = null;
    passwordModalTargetId = null;
}

async function submitPasswordModal() {
    const currentPassword = document.getElementById('currentPasswordInput').value.trim();
    const newPassword = document.getElementById('newPasswordModalInput').value.trim();
    const confirmPassword = document.getElementById('confirmPasswordModalInput').value.trim();
    const submitBtn = document.getElementById('passwordModalSubmitBtn');

    if (newPassword.length < PASSWORD_MIN_LENGTH) {
        showToast(`Yeni şifre en az ${PASSWORD_MIN_LENGTH} karakter olmalıdır.`, 'error');
        return;
    }
    if (newPassword !== confirmPassword) {
        showToast('Yeni şifreler eşleşmiyor.', 'error');
        return;
    }

    const isSelf = passwordModalMode === 'self';
    // Kendi şifresi: o anki oturumun token'ı kullanılır (admin paneli veya çalışan ekranı)
    const tokenKey = currentAdminUser ? 'attendance_admin_token' : 'attendance_user_token';
    const originalText = submitBtn.innerHTML;

    try {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Kaydediliyor...`;

        const response = isSelf
            ? await authFetch(tokenKey, '/api/v1/auth/change-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ CurrentPassword: currentPassword, NewPassword: newPassword })
            })
            : await adminFetch(`/api/v1/admin/users/${passwordModalTargetId}/password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ NewPassword: newPassword })
            });

        const data = await response.json();
        if (!response.ok) throw new Error(apiErrorMessage(data, 'Şifre güncellenemedi.'));

        // Şifre değişince eski oturum token'ları geçersiz olur; bu oturum yeni token ile devam eder
        if (isSelf && data.token) sessionStorage.setItem(tokenKey, data.token);

        closePasswordModal();
        showToast(data.message || 'Şifre güncellendi.', 'success');
    } catch (err) {
        console.error("submitPasswordModal error:", err);
        if (err.message !== 'Yetkisiz erişim.') showToast(`Hata: ${err.message}`, 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
    }
}

// ----------------------------------------------------
// History & Confirmation Modals
// ----------------------------------------------------

function openHistoryModal() {
    if (!currentUserId) return;
    historyModal.classList.remove('hidden-modal');
    fetchUserHistory(currentUserId);
}

function closeHistoryModal() {
    historyModal.classList.add('hidden-modal');
}

function openConfirmationModal(actionType) {
    if (!confirmationModal) return;
    pendingActionType = actionType;

    const isCheckIn = actionType === 'CHECK_IN';

    if (confirmModalTitle) {
        confirmModalTitle.textContent = isCheckIn ? 'İşe Başlama (Check-In) Onayı' : 'Mesai Bitirme (Check-Out) Onayı';
    }

    if (confirmActionBadge) {
        confirmActionBadge.className = isCheckIn ? 'badge-tag badge-checkin' : 'badge-tag badge-checkout';
        confirmActionBadge.textContent = isCheckIn ? 'GİRİŞ (CHECK-IN)' : 'ÇIKIŞ (CHECK-OUT)';
    }

    if (confirmTimeVal) {
        confirmTimeVal.textContent = formatDate(new Date().toISOString());
    }

    if (confirmLocationVal) {
        confirmLocationVal.textContent = locationDescInput ? locationDescInput.value.trim() : '';
    }

    if (confirmAddressVal) {
        confirmAddressVal.textContent = currentResolvedAddress || 'Adres Alınıyor / Belirtilmedi';
    }

    if (confirmDeviceVal) {
        const deviceInfo = detectDeviceInfo();
        confirmDeviceVal.textContent = `${deviceInfo.device} - ${deviceInfo.browser}`;
    }

    if (confirmSubmitBtn) {
        confirmSubmitBtn.disabled = false;
        confirmSubmitBtn.innerHTML = `<i class="fa-solid fa-check"></i> <span>Onayla ve Kaydet</span>`;
    }

    confirmationModal.classList.remove('hidden-modal');
}

function closeConfirmationModal() {
    pendingActionType = null;
    if (confirmationModal) confirmationModal.classList.add('hidden-modal');
}

// ----------------------------------------------------
// API Service Calls & Action Handling
// ----------------------------------------------------

async function loadUserData(userId) {
    await Promise.all([
        fetchUserStatus(userId),
        fetchUserHistory(userId)
    ]);
}

async function fetchUserStatus(userId) {
    try {
        if (statusBadge) {
            statusBadge.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Yükleniyor...`;
            statusBadge.className = "status-badge status-offline";
        }

        const response = await userFetch(`/api/v1/attendance/status/${userId}`);
        if (!response.ok) throw new Error('Durum bilgisi alınamadı.');

        const data = await response.json();
        
        if (data.UserID) {
            currentNumericUserId = data.UserID;
        }

        if (userWelcomeText) {
            userWelcomeText.textContent = data.FullName ? `Hoş geldiniz, ${data.FullName}` : `Hoş geldiniz`;
        }
        if (modalUserSubtitle) {
            modalUserSubtitle.textContent = data.FullName ? `${data.FullName}` : `Mesai Geçmişi`;
        }

        updateStatusCardUI(data);
    } catch (err) {
        console.error("fetchUserStatus error:", err);
        if (statusBadge) {
            statusBadge.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> Hata`;
        }
        showToast('Kullanıcı durumu alınırken hata oluştu.', 'error');
    }
}

async function fetchUserHistory(userId) {
    try {
        if (historyTableBody) {
            historyTableBody.innerHTML = `<tr><td colspan="4" class="text-center py-4"><i class="fa-solid fa-spinner fa-spin"></i> Geçmiş kayıtlar yükleniyor...</td></tr>`;
        }

        const response = await userFetch(`/api/v1/attendance/history/${userId}?limit=50`);
        if (!response.ok) throw new Error('Geçmiş kayıtlar alınamadı.');

        const historyList = await response.json();
        renderHistoryTableUI(historyList);
    } catch (err) {
        console.error("fetchUserHistory error:", err);
        if (historyTableBody) {
            historyTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-danger py-4">Kayıtlar yüklenemedi.</td></tr>`;
        }
    }
}

function handleAttendanceAction(actionType) {
    if (isSubmitting) {
        console.warn('İşlem devam ediyor, mükerrer tıklama engellendi.');
        return;
    }

    if (!currentUserId) {
        showToast('Lütfen önce sisteme giriş yapınız.', 'error');
        showLoginView();
        return;
    }

    if (actionType === 'CHECK_IN' && isUserCheckedIn) {
        showToast('Zaten işe başladınız. Tekrar giriş yapamazsınız.', 'warning');
        return;
    }

    if (actionType === 'CHECK_OUT' && !isUserCheckedIn) {
        showToast('Zaten mesai dışındasınız. Önce işe başla (Check-In) yapmalısınız.', 'warning');
        return;
    }

    const locationDesc = locationDescInput ? locationDescInput.value.trim() : '';
    if (!locationDesc) {
        showToast('Lütfen konum/şantiye açıklamasını giriniz.', 'error');
        if (locationDescInput) locationDescInput.focus();
        return;
    }

    // Açılan onay modal penceresinde bilgileri göster
    openConfirmationModal(actionType);
}

async function executePendingAttendanceAction() {
    if (!pendingActionType || isSubmitting) return;

    const actionType = pendingActionType;
    const locationDesc = locationDescInput ? locationDescInput.value.trim() : '';

    isSubmitting = true;

    if (confirmSubmitBtn) {
        confirmSubmitBtn.disabled = true;
        confirmSubmitBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Kaydediliyor...`;
    }

    try {
        const payload = {
            LocationDescription: locationDesc,
            Latitude: currentGpsCoords ? currentGpsCoords.latitude : null,
            Longitude: currentGpsCoords ? currentGpsCoords.longitude : null,
            DeviceInfo: detectDeviceInfo().device,
            ResolvedAddress: currentResolvedAddress
        };

        const endpoint = actionType === 'CHECK_IN' 
            ? '/api/v1/attendance/check-in' 
            : '/api/v1/attendance/check-out';

        const response = await userFetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'İşlem başarısız.');
        }

        const savedLog = await response.json();

        // Onay penceresini kapat
        closeConfirmationModal();

        // Kullanıcı durumunu ve geçmişini yenile
        await loadUserData(currentUserId);

        const actionText = actionType === 'CHECK_IN' ? 'İşe başlama' : 'Mesai bitirme';
        showToast(`${actionText} kaydınız başarıyla veritabanına kaydedildi.`, 'success');

    } catch (err) {
        console.error("executePendingAttendanceAction error:", err);
        showToast(`Hata: ${err.message}`, 'error');
    } finally {
        isSubmitting = false;
        if (confirmSubmitBtn) {
            confirmSubmitBtn.disabled = false;
            confirmSubmitBtn.innerHTML = `<i class="fa-solid fa-check"></i> <span>Onayla ve Kaydet</span>`;
        }
    }
}

// ----------------------------------------------------
// UI Render Helpers
// ----------------------------------------------------

function updateStatusCardUI(data) {
    isUserCheckedIn = !!data.is_checked_in;

    if (statusBadge) {
        if (isUserCheckedIn) {
            statusBadge.className = "status-badge status-online";
            statusBadge.innerHTML = `<i class="fa-solid fa-circle"></i> MESAİDE (İÇERİDE)`;
        } else {
            statusBadge.className = "status-badge status-offline";
            statusBadge.innerHTML = `<i class="fa-solid fa-circle"></i> MESAİ DIŞINDA`;
        }
    }

    if (checkInBtn) {
        checkInBtn.disabled = isUserCheckedIn;
        if (isUserCheckedIn) {
            checkInBtn.classList.add('disabled-btn');
            checkInBtn.title = "Zaten işe başladınız. Tekrar giriş yapamazsınız.";
        } else {
            checkInBtn.classList.remove('disabled-btn');
            checkInBtn.removeAttribute('title');
        }
    }

    if (checkOutBtn) {
        checkOutBtn.disabled = !isUserCheckedIn;
        if (isUserCheckedIn) {
            checkOutBtn.classList.remove('disabled-btn');
            checkOutBtn.removeAttribute('title');
        } else {
            checkOutBtn.classList.add('disabled-btn');
            checkOutBtn.title = "Zaten mesai dışındasınız. Önce işe başla (Check-In) yapmalısınız.";
        }
    }

    if (lastActionVal) {
        lastActionVal.textContent = data.last_action ? (data.last_action === 'CHECK_IN' ? 'GİRİŞ (Check-In)' : 'ÇIKIŞ (Check-Out)') : 'Kayıt Bulunmadı';
    }
    if (lastLocationVal) {
        lastLocationVal.textContent = data.last_location || '-';
    }
    if (lastTimeVal) {
        lastTimeVal.textContent = data.last_log_time ? formatDate(data.last_log_time) : '-';
    }
}

function renderHistoryTableUI(list) {
    if (!historyTableBody) return;
    if (!list || list.length === 0) {
        historyTableBody.innerHTML = `<tr><td colspan="4" class="text-center py-4">Henüz mesai kaydı bulunmuyor.</td></tr>`;
        return;
    }

    let rowsHtml = '';
    list.forEach(item => {
        const isCheckIn = item.ActionType === 'CHECK_IN';
        const badgeClass = isCheckIn ? 'badge-checkin' : 'badge-checkout';
        const actionLabel = isCheckIn ? 'GİRİŞ' : 'ÇIKIŞ';

        rowsHtml += `
            <tr>
                <td><span class="badge-tag ${badgeClass}">${actionLabel}</span></td>
                <td>${formatDate(item.LogDateTime)}</td>
                <td><strong>${escapeHtml(item.LocationDescription)}</strong></td>
                <td><small class="text-muted">${escapeHtml(item.ResolvedAddress || '-')}</small></td>
            </tr>
        `;
    });

    historyTableBody.innerHTML = rowsHtml;
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    
    return d.toLocaleString('tr-TR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

function escapeHtml(text) {
    if (!text) return '';
    return text.replace(/[&<>"']/g, function(m) {
        return {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        }[m];
    });
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    let iconClass = 'fa-circle-info';
    if (type === 'success') iconClass = 'fa-circle-check';
    if (type === 'error') iconClass = 'fa-circle-exclamation';

    toast.innerHTML = `<i class="fa-solid ${iconClass}"></i> <span>${escapeHtml(message)}</span>`;
    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s reverse forwards';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Window Global Attachments for Fail-Proof Inline Handlers
window.onEmployeeSelectChange = onEmployeeSelectChange;
window.setEmployeeReportRange = setEmployeeReportRange;
window.applyCustomDateFilter = applyCustomDateFilter;
window.fetchEmployeeAttendanceReport = fetchEmployeeAttendanceReport;
window.populateEmployeeDropdown = populateEmployeeDropdown;
