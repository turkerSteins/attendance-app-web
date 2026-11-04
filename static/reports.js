/**
 * Personel Çalışma Süreleri ve Excel Raporlama Sayfası JavaScript Kontrolcüsü
 */

let currentPeriod = 'weekly';
let currentSearch = '';
let searchDebounceTimer = null;
let cachedReportData = null;

// Sayfa yüklendiğinde çalışacak başlatıcı
document.addEventListener('DOMContentLoaded', () => {
    checkAdminSession();
    initDefaultDates();
    loadReportData();
});

// Admin oturum kontrolü
function checkAdminSession() {
    const adminToken = sessionStorage.getItem('attendance_admin_token');
    const adminUser = sessionStorage.getItem('attendance_admin_user');
    
    if (!adminToken) {
        alert("Bu sayfaya erişmek için önce Yönetici Girişi yapmanız gerekmektedir.");
        window.location.href = "/";
    }
}

// Tarih seçicileri için varsayılan tarihleri belirle (Son 7 gün)
function initDefaultDates() {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - 7);

    const startInput = document.getElementById('startDateInput');
    const endInput = document.getElementById('endDateInput');
    if (startInput && endInput) {
        startInput.value = formatDateForInput(start);
        endInput.value = formatDateForInput(end);
    }
}

function formatDateForInput(d) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

// Dönem Değiştirme (Bugün / Bu Hafta / Bu Ay / Özel vb.)
function setPeriod(period) {
    currentPeriod = period;

    // Aktif buton stilini güncelle
    document.querySelectorAll('.range-pill-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-range') === period);
    });

    const customRow = document.getElementById('customDateRow');
    if (customRow) {
        customRow.style.display = (period === 'custom') ? 'flex' : 'none';
    }

    loadReportData();
}

// Arama kutusu anlık filtreleme
function onSearchChange() {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
        currentSearch = document.getElementById('searchInput').value.trim();
        loadReportData();
    }, 300);
}

// API'den Rapor Verilerini Yükleme
async function loadReportData() {
    const token = sessionStorage.getItem('attendance_admin_token');
    if (!token) return;

    const tbody = document.getElementById('reportTableBody');
    tbody.innerHTML = `
        <tr>
            <td colspan="10" style="text-align:center; padding: 40px; color: var(--text-muted);">
                <i class="fa-solid fa-spinner fa-spin" style="font-size: 1.5rem; margin-bottom: 8px; display:block; color:#2E7D32;"></i>
                Personel mesai süreleri hesaplanıyor, lütfen bekleyin...
            </td>
        </tr>
    `;

    try {
        let url = `/api/v1/admin/reports/work-hours?range=${encodeURIComponent(currentPeriod)}`;
        if (currentPeriod === 'custom') {
            const startVal = document.getElementById('startDateInput').value;
            const endVal = document.getElementById('endDateInput').value;
            if (startVal) url += `&start_date=${encodeURIComponent(startVal)}`;
            if (endVal) url += `&end_date=${encodeURIComponent(endVal)}`;
        }
        if (currentSearch) {
            url += `&search=${encodeURIComponent(currentSearch)}`;
        }

        const response = await fetch(url, {
            headers: {
                'Authorization': `Bearer ${token}`,
                'Accept': 'application/json'
            }
        });

        if (response.status === 401 || response.status === 403) {
            alert("Oturum süreniz dolmuş veya yönetici yetkiniz bulunmuyor. Lütfen tekrar giriş yapın.");
            sessionStorage.removeItem('attendance_admin_token');
            window.location.href = "/";
            return;
        }

        if (!response.ok) {
            let errorMsg = `Sunucu hatası (${response.status})`;
            try {
                const errData = await response.json();
                if (errData && errData.detail) errorMsg = errData.detail;
            } catch (_) {}
            throw new Error(errorMsg);
        }

        const data = await response.json();
        cachedReportData = data;
        renderReportView(data);

    } catch (err) {
        console.error("Rapor yüklenirken hata:", err);
        tbody.innerHTML = `
            <tr>
                <td colspan="10" style="text-align:center; padding: 30px; color: var(--error);">
                    <i class="fa-solid fa-triangle-exclamation" style="font-size: 1.5rem; margin-bottom: 8px; display:block;"></i>
                    Rapor verileri alınamadı: ${err.message}
                </td>
            </tr>
        `;
    }
}

// Verileri Ekrana Çizme (KPI Kartları + Tablo)
function renderReportView(data) {
    // 1. KPI Kartlarını Güncelle
    document.getElementById('kpiTotalPersonnel').textContent = data.total_personnel_count || 0;
    document.getElementById('kpiActivePersonnel').textContent = data.total_active_personnel || 0;
    document.getElementById('kpiTotalHours').textContent = `${(data.total_hours_sum || 0).toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 2 })} Sa`;
    document.getElementById('kpiAvgHours').textContent = `${(data.average_hours || 0).toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 2 })} Sa`;
    
    document.getElementById('recordCountBadge').textContent = `${data.items.length} Personel`;

    // 2. Tabloyu Doldur
    const tbody = document.getElementById('reportTableBody');
    if (!data.items || data.items.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" style="text-align:center; padding: 36px; color: var(--text-muted);">
                    <i class="fa-solid fa-folder-open" style="font-size: 1.6rem; margin-bottom: 8px; display:block; opacity: 0.5;"></i>
                    Seçilen kriterlere ve tarih aralığına uygun personel kaydı bulunamadı.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = data.items.map((item, idx) => {
        const statusBadge = item.IsCurrentlyActive
            ? `<span class="badge-status badge-active">Mesaide</span>`
            : `<span class="badge-status badge-idle">Dışarıda</span>`;

        const roleBadge = item.Role === 'ADMIN'
            ? `<span style="color:#B45309; background:#FEF3C7; padding:2px 8px; border-radius:4px; font-weight:700; font-size:0.75rem;">YÖNETİCİ</span>`
            : `<span style="color:#1D4ED8; background:#DBEAFE; padding:2px 8px; border-radius:4px; font-weight:700; font-size:0.75rem;">SAHA ÇALIŞANI</span>`;

        const hoursDisplay = item.TotalWorkHours > 0
            ? `<span class="hours-highlight">${item.TotalWorkHours.toFixed(2)}</span> <span style="font-size:0.8rem; color:var(--text-muted);">saat</span>`
            : `<span style="color:var(--text-muted);">-</span>`;

        return `
            <tr>
                <td style="text-align: center; color: var(--text-muted); font-weight: 600;">${idx + 1}</td>
                <td><strong style="color: #1E293B;">${escapeHtml(item.EmployeeCode)}</strong></td>
                <td>
                    <div style="font-weight: 600; color: var(--text-main);">${escapeHtml(item.FullName)}</div>
                </td>
                <td>${roleBadge}</td>
                <td style="text-align: center; font-weight: 600;">${item.DaysWorked} gün</td>
                <td style="text-align: center; color: var(--text-muted); font-size: 0.85rem;">
                    <span style="color:#15803D; font-weight:700;">${item.TotalCheckIns} Giriş</span> / 
                    <span style="color:#B91C1C; font-weight:700;">${item.TotalCheckOuts} Çıkış</span>
                </td>
                <td style="text-align: right;">${hoursDisplay}</td>
                <td style="font-weight: 600; color: #2D3748;">${escapeHtml(item.FormattedWorkDuration)}</td>
                <td style="text-align: center;">${statusBadge}</td>
                <td style="text-align: center;">
                    <button type="button" class="btn-view-logs" onclick="openDetailModal(${item.UserID}, '${escapeHtml(item.FullName)}', '${escapeHtml(item.EmployeeCode)}', '${escapeHtml(item.FormattedWorkDuration)}')">
                        <i class="fa-solid fa-list-check"></i>
                        <span>Detay</span>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

// Excel Olarak İndir (.xlsx)
async function exportToExcel() {
    const btn = document.getElementById('btnExportExcel');
    const token = sessionStorage.getItem('attendance_admin_token');
    if (!token) return;

    try {
        btn.classList.add('loading');
        btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> <span>Excel Hazırlanıyor...</span>`;

        let url = `/api/v1/admin/reports/work-hours/export-excel?range=${encodeURIComponent(currentPeriod)}`;
        if (currentPeriod === 'custom') {
            const startVal = document.getElementById('startDateInput').value;
            const endVal = document.getElementById('endDateInput').value;
            if (startVal) url += `&start_date=${encodeURIComponent(startVal)}`;
            if (endVal) url += `&end_date=${encodeURIComponent(endVal)}`;
        }
        if (currentSearch) {
            url += `&search=${encodeURIComponent(currentSearch)}`;
        }

        const response = await fetch(url, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            throw new Error(`Excel indirilemedi (Kod: ${response.status})`);
        }

        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;

        // Dosya adını belirleme
        const contentDisp = response.headers.get('Content-Disposition');
        let filename = `Personel_Mesai_Raporu_${currentPeriod}.xlsx`;
        if (contentDisp && contentDisp.includes('filename=')) {
            filename = contentDisp.split('filename=')[1].replace(/["']/g, '');
        }

        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(downloadUrl);

    } catch (err) {
        console.error("Excel indirme hatası:", err);
        alert("Excel dosyası oluşturulurken bir hata meydana geldi: " + err.message);
    } finally {
        btn.classList.remove('loading');
        btn.innerHTML = `<i class="fa-solid fa-file-excel"></i> <span>Excel Olarak İndir (.xlsx)</span>`;
    }
}

// Detay Hareket Modalını Aç
async function openDetailModal(userId, fullName, empCode, durationText) {
    const modal = document.getElementById('detailModal');
    const logsBody = document.getElementById('modalLogsBody');

    document.getElementById('modalEmployeeName').textContent = fullName;
    document.getElementById('modalEmployeeCode').textContent = `Sicil No: ${empCode}`;
    document.getElementById('modalTotalHours').textContent = `Toplam Çalışma: ${durationText}`;

    const periodLabels = {
        daily: 'Bugün',
        weekly: 'Son 7 Gün',
        monthly: 'Son 30 Gün',
        all: 'Tüm Zamanlar',
        custom: 'Seçilen Tarih Aralığı'
    };
    document.getElementById('modalPeriodText').textContent = `Periyot: ${periodLabels[currentPeriod] || currentPeriod}`;

    logsBody.innerHTML = `
        <tr>
            <td colspan="5" style="text-align:center; padding:24px; color:var(--text-muted);">
                <i class="fa-solid fa-spinner fa-spin" style="margin-bottom:6px; display:block;"></i>
                Hareket kayıtları yükleniyor...
            </td>
        </tr>
    `;

    modal.classList.add('active');

    try {
        const token = sessionStorage.getItem('attendance_admin_token');
        let url = `/api/v1/admin/reports/employee?employeeId=${encodeURIComponent(userId)}&range=${encodeURIComponent(currentPeriod)}`;
        if (currentPeriod === 'custom') {
            const startVal = document.getElementById('startDateInput').value;
            const endVal = document.getElementById('endDateInput').value;
            if (startVal) url += `&start_date=${encodeURIComponent(startVal)}`;
            if (endVal) url += `&end_date=${encodeURIComponent(endVal)}`;
        }

        const res = await fetch(url, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!res.ok) throw new Error("Kayıtlar alınamadı");

        const data = await res.json();
        const records = data.records || [];

        if (records.length === 0) {
            logsBody.innerHTML = `
                <tr>
                    <td colspan="5" style="text-align:center; padding:20px; color:var(--text-muted);">
                        Bu tarih aralığında kaydedilmiş mesai hareketi bulunmuyor.
                    </td>
                </tr>
            `;
            return;
        }

        logsBody.innerHTML = records.map(log => {
            const isCheckIn = log.ActionType === 'CHECK_IN';
            const actionTag = isCheckIn
                ? `<span class="action-tag-in"><i class="fa-solid fa-arrow-right-to-bracket"></i> GİRİŞ</span>`
                : `<span class="action-tag-out"><i class="fa-solid fa-arrow-right-from-bracket"></i> ÇIKIŞ</span>`;

            const dateStr = formatDateTime(log.LogDateTime);

            return `
                <tr>
                    <td style="font-weight:600; white-space:nowrap;">${dateStr}</td>
                    <td>${actionTag}</td>
                    <td>${escapeHtml(log.LocationDescription || log.ResolvedAddress || '-')}</td>
                    <td style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(log.DeviceInfo || '-')}</td>
                    <td style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(log.IPAddress || '-')}</td>
                </tr>
            `;
        }).join('');

    } catch (err) {
        logsBody.innerHTML = `
            <tr>
                <td colspan="5" style="text-align:center; padding:20px; color:var(--error);">
                    Hata: ${err.message}
                </td>
            </tr>
        `;
    }
}

function closeDetailModal(e) {
    if (e && e.target && e.target !== e.currentTarget && !e.target.classList.contains('modal-close-btn') && !e.target.closest('.modal-close-btn')) {
        return;
    }
    const modal = document.getElementById('detailModal');
    if (modal) modal.classList.remove('active');
}

function handleLogout() {
    sessionStorage.removeItem('attendance_admin_token');
    sessionStorage.removeItem('attendance_admin_user');
    window.location.href = "/";
}

function formatDateTime(dtStr) {
    if (!dtStr) return '-';
    try {
        const d = new Date(dtStr);
        return d.toLocaleString('tr-TR', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } catch {
        return dtStr;
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

