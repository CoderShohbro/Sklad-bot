// Telegram Web App SDK Initialisation
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
}

// Override global fetch to automatically inject Telegram Web App Signature Header
const originalFetch = window.fetch;
window.fetch = async function (resource, options = {}) {
    if (tg && tg.initData) {
        if (!options.headers) {
            options.headers = {};
        }
        if (options.headers instanceof Headers) {
            options.headers.set("X-Telegram-Init-Data", tg.initData);
        } else {
            options.headers["X-Telegram-Init-Data"] = tg.initData;
        }
    }
    return originalFetch(resource, options);
};

// State Management
// ULANISH KO'RSATMASI:
// 1. Agar Frontend va Backend bitta serverda bo'lsa (FastAPI orqali tarqatilsa): "" (bo'sh) qoldiring.
// 2. Agar Frontend alohida hostingda (Netlify, Vercel va h.k.) bo'lsa, backend serveringizning HTTPS havolasini yozing.
//    Masalan: let API_URL = "https://api.baraka-sklad.uz";
let API_URL = "https://api.baraka-sklad.uz"; 
let state = {
    products: [],
    categories: [],
    warehouses: [],
    customers: [],
    isOnline: navigator.onLine,
    scannedProduct: null
};

let turnoverChartInstance = null;
let categoryChartInstance = null;

// Initialize App
document.addEventListener("DOMContentLoaded", async () => {
    initNetworkMonitoring();
    setupEventListeners();
    await fetchUserProfile(); // Role profiling must complete first
    loadAllData();
    
    // Set up auto-refresh every 30 seconds if online
    setInterval(() => {
        if (state.isOnline) {
            loadAllData();
        }
    }, 30000);
});

// --- NETWORK MONITORING & OFFLINE SYNC ---
function initNetworkMonitoring() {
    updateOnlineStatus();
    
    window.addEventListener("online", () => {
        state.isOnline = true;
        updateOnlineStatus();
        showToast("Internet aloqasi tiklandi! Sinxronizatsiya qilinmoqda...", "success");
        syncOfflineQueue();
    });
    
    window.addEventListener("offline", () => {
        state.isOnline = false;
        updateOnlineStatus();
        showToast("Internet uzildi. Tizim oflayn rejimda ishlamoqda.", "error");
    });
}

function updateOnlineStatus() {
    const statusBadg = document.getElementById("connection-status");
    const statusTxt = document.getElementById("status-text");
    
    if (state.isOnline) {
        statusBadg.className = "status-badge online";
        statusTxt.innerText = "Online";
    } else {
        statusBadg.className = "status-badge offline";
        statusTxt.innerText = "Oflayn (Kesh)";
    }
}

function getOfflineQueue() {
    const queue = localStorage.getItem("baraka_offline_queue");
    return queue ? JSON.parse(queue) : [];
}

function saveOfflineQueue(queue) {
    localStorage.setItem("baraka_offline_queue", JSON.stringify(queue));
}

async function syncOfflineQueue() {
    const queue = getOfflineQueue();
    if (queue.length === 0) return;
    
    try {
        const response = await fetch(`${API_URL}/api/sync`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(queue)
        });
        
        const result = await response.json();
        if (response.ok) {
            showToast(`Keshdagi ${result.synced_count} ta amal muvaffaqiyatli sinxronizatsiya qilindi!`, "success");
            saveOfflineQueue([]); // Clear queue
            loadAllData(); // Reload all fresh data
            if (tg) tg.HapticFeedback.notificationOccurred("success");
        } else {
            showToast("Sinxronizatsiyada xatolik yuz berdi.", "error");
        }
    } catch (error) {
        console.error("Sync error:", error);
    }
}

// Save transaction to local queue when offline
function queueOfflineTransaction(tx) {
    const queue = getOfflineQueue();
    queue.push(tx);
    saveOfflineQueue(queue);
    
    // Simulate stock change locally so UI looks correct immediately
    applyLocalStockUpdate(tx);
    showToast("Amal keshda saqlandi (Oflayn)", "info");
    if (tg) tg.HapticFeedback.impactOccurred("medium");
}

function applyLocalStockUpdate(tx) {
    // Modify state locally
    const prod = state.products.find(p => p.id === parseInt(tx.product_id));
    if (prod) {
        const stock = prod.stocks.find(s => s.warehouse_id === parseInt(tx.warehouse_id));
        const qty = parseFloat(tx.quantity);
        
        if (tx.type === "Kirim" && stock) {
            stock.quantity += qty;
        } else if (tx.type === "Chiqim" && stock) {
            stock.quantity -= qty;
            if (tx.customer_id) {
                const cust = state.customers.find(c => c.id === parseInt(tx.customer_id));
                if (cust) cust.balance -= qty * prod.selling_price;
            }
        } else if (tx.type === "Transfer" && stock) {
            stock.quantity -= qty;
            const targetStock = prod.stocks.find(s => s.warehouse_id === parseInt(tx.target_warehouse_id));
            if (targetStock) targetStock.quantity += qty;
        } else if (tx.type === "Spisat" && stock) {
            stock.quantity -= qty;
        }
    }
    
    // Rerender tables with simulated state
    renderProducts(state.products);
    renderCustomers(state.customers);
}

// --- SETUP EVENT LISTENERS ---
function setupEventListeners() {
    // Search input handler
    document.getElementById("search-query").addEventListener("input", (e) => {
        handleSearch(e.target.value);
    });
    
    // Category filter handler
    document.getElementById("filter-category").addEventListener("change", (e) => {
        handleSearch(document.getElementById("search-query").value);
    });
    
    // Scanner integration button
    document.getElementById("scan-barcode-btn").addEventListener("click", () => {
        scanBarcode("search-query");
    });
    
    // Scanner inside new product modal
    document.getElementById("scan-barcode-modal-btn").addEventListener("click", () => {
        scanBarcode("p-barcode");
    });
    
    // Excel export button
    document.getElementById("export-excel-btn").addEventListener("click", () => {
        window.location.href = `${API_URL}/api/export/excel`;
    });
}

function scanBarcode(targetInputId) {
    if (tg && typeof tg.showScanQrPopup === "function") {
        tg.showScanQrPopup({ text: "Tovar shtrix-kodini skanerlang 📸" }, (text) => {
            document.getElementById(targetInputId).value = text;
            tg.closeScanQrPopup();
            tg.HapticFeedback.notificationOccurred("success");
            
            if (targetInputId === "search-query") {
                processScannedBarcode(text);
            }
            return true;
        });
    } else {
        // Fallback for browser tests
        const mockBarcode = prompt("Shtrix-kodni qo'lda kiriting (Kamera emulyatsiyasi):");
        if (mockBarcode) {
            document.getElementById(targetInputId).value = mockBarcode;
            if (targetInputId === "search-query") {
                processScannedBarcode(mockBarcode);
            }
        }
    }
}

window.toggleBarcodeDrawer = function(show) {
    const drawer = document.getElementById("barcode-drawer");
    if (!drawer) return;
    if (show) {
        drawer.classList.add("active");
    } else {
        drawer.classList.remove("active");
    }
};

window.processScannedBarcode = function(barcode) {
    const prod = state.products.find(p => p.barcode === barcode);
    if (prod) {
        state.scannedProduct = prod;
        
        document.getElementById("drawer-product-name").innerText = prod.name;
        document.getElementById("drawer-product-barcode").innerText = `Shtrix-kod: ${prod.barcode}`;
        
        const totalQty = prod.stocks.reduce((acc, st) => acc + st.quantity, 0);
        document.getElementById("drawer-product-stock").innerText = `${totalQty} dona/qop/metr`;
        
        toggleBarcodeDrawer(true);
        if (tg) tg.HapticFeedback.notificationOccurred("success");
    } else {
        if (confirm(`"${barcode}" shtrix-kodli mahsulot topilmadi. Yangi tovar qo'shishni xohlaysizmi?`)) {
            openModal("modal-new-product");
            document.getElementById("p-barcode").value = barcode;
            document.getElementById("p-name").focus();
            if (tg) tg.HapticFeedback.impactOccurred("medium");
        }
    }
};

window.triggerDrawerAction = function(action) {
    if (!state.scannedProduct) return;
    
    const prodId = state.scannedProduct.id;
    toggleBarcodeDrawer(false);
    
    if (action === "kirim") {
        openModal("modal-kirim");
        document.getElementById("k-product").value = prodId;
    } else if (action === "chiqim") {
        openModal("modal-chiqim");
        document.getElementById("c-product").value = prodId;
        updateChiqimMaxLimit();
    } else if (action === "transfer") {
        openModal("modal-transfer");
        document.getElementById("t-product").value = prodId;
        updateTransferMaxLimit();
    }
};

// --- SEARCH & FILTER ---
function handleSearch(query) {
    const cleanQuery = query.trim().toLowerCase();
    const catFilter = document.getElementById("filter-category").value;
    
    let filtered = state.products;
    
    if (cleanQuery) {
        filtered = filtered.filter(p => 
            p.name.toLowerCase().includes(cleanQuery) || 
            p.barcode.includes(cleanQuery)
        );
    }
    
    if (catFilter) {
        filtered = filtered.filter(p => p.category_id === parseInt(catFilter));
    }
    
    renderProducts(filtered);
}

// --- TAB SWITCHER ---
window.switchTab = function(tabName) {
    // Hide all sections
    document.querySelectorAll(".view-section").forEach(s => s.classList.add("hidden"));
    // Show selected section
    document.getElementById(`view-${tabName}`).classList.remove("hidden");
    
    // Update active state in bottom nav
    document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
    
    // Find current nav item
    const navItems = document.querySelectorAll(".nav-item");
    if (tabName === "dashboard") navItems[0].classList.add("active");
    if (tabName === "stocks") navItems[1].classList.add("active");
    if (tabName === "customers") navItems[2].classList.add("active");
    if (tabName === "history") navItems[3].classList.add("active");
    
    if (tg) tg.HapticFeedback.impactOccurred("light");
};

// --- DATA LOADERS ---
async function loadAllData() {
    if (!state.isOnline) return; 
    
    try {
        const loaders = [
            fetchDashboardStats(),
            fetchChartData(),
            fetchDashboardWidgets(),
            fetchProducts(),
            fetchCategories(),
            fetchWarehouses(),
            fetchCustomers(),
            fetchTransactionsHistory()
        ];
        
        // Admin gets employee list too
        if (state.currentUser?.role === "Admin") {
            loaders.push(fetchEmployees());
        }
        
        await Promise.all(loaders);
        
        // Sync any offline records once if online
        syncOfflineQueue();
        
    } catch (error) {
        console.error("Ma'lumotlarni yuklashda xato:", error);
    }
}

async function fetchUserProfile() {
    try {
        const res = await fetch(`${API_URL}/api/users/me`);
        if (res.ok) {
            state.currentUser = await res.json();
            applyRolePermissions();
        }
    } catch (e) {
        console.error("Profil yuklashda xatolik:", e);
    }
}

function applyRolePermissions() {
    const role = state.currentUser?.role || "Skladchi";
    if (role !== "Admin") {
        // Hide admin-only sections visually
        document.querySelectorAll(".admin-only").forEach(el => {
            el.style.setProperty("display", "none", "important");
        });
        
        // Hide cost statistics
        const foydaCard = document.getElementById("metric-foyda-card");
        const kirimCard = document.getElementById("metric-kirim-card");
        const chiqimCard = document.getElementById("metric-chiqim-card");
        if (foydaCard) foydaCard.style.display = "none";
        if (kirimCard) kirimCard.style.display = "none";
        if (chiqimCard) chiqimCard.style.display = "none";
        
        // Update metrics grid to render 1 card or simple layout
        const grid = document.querySelector(".metrics-grid");
        if (grid) {
            grid.className = "metrics-grid grid grid-cols-1 gap-3";
        }
        
        // Hide cost inputs
        const costInput = document.getElementById("p-cost");
        if (costInput) {
            costInput.closest(".form-group")?.style.setProperty("display", "none", "important");
        }
        
        // Excel download button
        const excelBtn = document.getElementById("export-excel-btn");
        if (excelBtn) excelBtn.style.display = "none";
    } else {
        // Show everything for Admin
        document.querySelectorAll(".admin-only").forEach(el => {
            el.style.display = "";
        });
    }
}

async function fetchEmployees() {
    try {
        const res = await fetch(`${API_URL}/api/users`);
        if (res.ok) {
            const data = await res.json();
            renderEmployees(data);
        }
    } catch (e) {
        console.error("Ishchilar ro'yxatida xato:", e);
    }
}

function renderEmployees(list) {
    const container = document.getElementById("employees-list-container");
    if (!container) return;
    container.innerHTML = "";
    
    if (!list || list.length === 0) {
        container.innerHTML = '<div class="col-span-2 text-center text-slate-500 italic py-4">Xodimlar topilmadi.</div>';
        return;
    }
    
    list.forEach(emp => {
        const isSelf = emp.telegram_id === state.currentUser?.telegram_id;
        const activeBadge = emp.is_active 
            ? `<span class="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-xs px-2 py-0.5 rounded font-semibold">Faol</span>`
            : `<span class="bg-red-500/10 text-red-400 border border-red-500/20 text-xs px-2 py-0.5 rounded font-semibold">Bloklangan</span>`;
            
        container.innerHTML += `
            <div class="glass-panel p-4 flex flex-col justify-between gap-3">
                <div class="flex justify-between items-start">
                    <div>
                        <h4 class="font-bold text-slate-100">${emp.full_name} ${isSelf ? "(Siz)" : ""}</h4>
                        <p class="text-xs text-slate-400">Telegram ID: <span class="font-mono text-slate-300 font-semibold">${emp.telegram_id}</span></p>
                        <p class="text-xs text-slate-400">Username: <span class="font-mono text-indigo-400">@${emp.username || "yo'q"}</span></p>
                    </div>
                    ${activeBadge}
                </div>
                <div class="flex justify-between items-center border-t border-slate-800 pt-3 gap-2">
                    <div class="flex items-center gap-1.5 flex-1">
                        <span class="text-xs text-slate-400">Rol:</span>
                        <select class="bg-slate-800 border border-slate-700 text-xs text-slate-200 rounded px-2 py-1 flex-1" 
                                ${isSelf ? 'disabled' : ''} 
                                onchange="changeEmployeeRole(${emp.telegram_id}, this.value)">
                            <option value="Skladchi" ${emp.role === 'Skladchi' ? 'selected' : ''}>Skladchi</option>
                            <option value="Admin" ${emp.role === 'Admin' ? 'selected' : ''}>Admin</option>
                        </select>
                    </div>
                    ${!isSelf ? `
                        <button class="text-xs font-bold px-3 py-1 rounded ${emp.is_active ? 'bg-red-500/20 text-red-400 border border-red-500/30' : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'}"
                                onclick="toggleEmployeeStatus(${emp.telegram_id}, ${!emp.is_active})">
                            ${emp.is_active ? "Bloklash" : "Aktivlashtirish"}
                        </button>
                    ` : ''}
                </div>
            </div>
        `;
    });
}

window.changeEmployeeRole = async function(telegramId, newRole) {
    try {
        const res = await fetch(`${API_URL}/api/users/${telegramId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ role: newRole })
        });
        if (res.ok) {
            showToast("Xodim roli muvaffaqiyatli yangilandi!", "success");
            loadAllData();
        } else {
            showToast("Ruxsat yo'q yoki xatolik yuz berdi.", "error");
        }
    } catch (e) {
        showToast("Server xatosi.", "error");
    }
};

window.toggleEmployeeStatus = async function(telegramId, isActive) {
    try {
        const res = await fetch(`${API_URL}/api/users/${telegramId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ is_active: isActive })
        });
        if (res.ok) {
            showToast(isActive ? "Xodim aktivlashtirildi!" : "Xodim bloklandi!", "success");
            loadAllData();
        } else {
            showToast("Ruxsat yo'q yoki xatolik yuz berdi.", "error");
        }
    } catch (e) {
        showToast("Server xatosi.", "error");
    }
};

window.handleNewEmployee = async function(event) {
    event.preventDefault();
    const payload = {
        telegram_id: parseInt(document.getElementById("emp-tg-id").value),
        full_name: document.getElementById("emp-name").value,
        username: document.getElementById("emp-username").value || null,
        role: document.getElementById("emp-role").value
    };
    
    try {
        const res = await fetch(`${API_URL}/api/users`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            showToast("Yangi xodim muvaffaqiyatli ro'yxatdan o'tdi!", "success");
            closeModal("modal-new-employee");
            document.getElementById("form-new-employee").reset();
            loadAllData();
            if (tg) tg.HapticFeedback.notificationOccurred("success");
        } else {
            const data = await res.json();
            showToast(data.detail || "Xatolik yuz berdi.", "error");
        }
    } catch (e) {
        showToast("Server xatosi.", "error");
    }
};

async function fetchDashboardStats() {
    const res = await fetch(`${API_URL}/api/dashboard`);
    const data = await res.json();
    
    document.getElementById("stat-kirim").innerText = `${data.kirim_sum.toLocaleString()} UZS`;
    document.getElementById("stat-chiqim").innerText = `${data.chiqim_sum.toLocaleString()} UZS`;
    document.getElementById("stat-foyda").innerText = `${data.net_profit.toLocaleString()} UZS`;
    document.getElementById("stat-qoldiq").innerText = `${data.total_stock_count.toLocaleString()} dona`;
}

async function fetchChartData() {
    const res = await fetch(`${API_URL}/api/dashboard/chart`);
    const data = await res.json();
    renderChart(data);
}

async function fetchDashboardWidgets() {
    try {
        const res = await fetch(`${API_URL}/api/dashboard/widgets`);
        const data = await res.json();
        renderTopDebtors(data.top_debtors);
        renderCategoryChart(data.category_shares);
    } catch (e) {
        console.error("Widgets load error:", e);
    }
}

function renderTopDebtors(debtors) {
    const container = document.getElementById("top-debtors-list");
    if (!container) return;
    container.innerHTML = "";
    if (!debtors || debtors.length === 0) {
        container.innerHTML = '<div class="text-xs text-slate-500 italic">Qarzdor ustalar aniqlanmadi.</div>';
        return;
    }
    debtors.forEach(d => {
        container.innerHTML += `
            <div class="debtor-item">
                <span class="text-xs font-semibold text-slate-200">${d.name}</span>
                <span class="text-xs font-bold text-red-400 font-mono">${d.balance.toLocaleString()} UZS</span>
            </div>
        `;
    });
}

function renderCategoryChart(shares) {
    const canvas = document.getElementById("categoryChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    
    const labels = shares.map(s => s.category_name);
    const dataValues = shares.map(s => s.total_value);
    
    if (categoryChartInstance) {
        categoryChartInstance.destroy();
    }
    
    // Empty state fallback
    if (dataValues.reduce((a, b) => a + b, 0) === 0) {
        labels.push("Bo'sh");
        dataValues.push(1);
    }
    
    categoryChartInstance = new Chart(ctx, {
        type: "doughnut",
        data: {
            labels: labels,
            datasets: [{
                data: dataValues,
                backgroundColor: [
                    "#6366F1",
                    "#10B981",
                    "#06B6D4",
                    "#F59E0B",
                    "#EC4899"
                ],
                borderWidth: 1,
                borderColor: "#111827"
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        color: "#94A3B8",
                        boxWidth: 8,
                        font: { family: "Plus Jakarta Sans", size: 9 }
                    }
                }
            },
            cutout: "65%"
        }
    });
}

async function fetchProducts() {
    const res = await fetch(`${API_URL}/api/products`);
    state.products = await res.json();
    renderProducts(state.products);
    populateProductDropdowns();
    checkLowStockLevels();
}

async function fetchCategories() {
    const res = await fetch(`${API_URL}/api/categories`);
    state.categories = await res.json();
    
    // Populate filter dropdown
    const filterSelect = document.getElementById("filter-category");
    const newProdSelect = document.getElementById("p-category");
    
    // Keep first blank option for filter
    filterSelect.innerHTML = '<option value="">Barcha toifalar</option>';
    newProdSelect.innerHTML = '';
    
    state.categories.forEach(c => {
        filterSelect.innerHTML += `<option value="${c.id}">${c.name}</option>`;
        newProdSelect.innerHTML += `<option value="${c.id}">${c.name}</option>`;
    });
}

async function fetchWarehouses() {
    const res = await fetch(`${API_URL}/api/warehouses`);
    state.warehouses = await res.json();
    
    // Populate selects
    const w1 = document.getElementById("p-warehouse");
    const w2 = document.getElementById("k-warehouse");
    const w3 = document.getElementById("c-warehouse");
    const w4 = document.getElementById("t-src-warehouse");
    const w5 = document.getElementById("t-dst-warehouse");
    
    [w1, w2, w3, w4, w5].forEach(s => s.innerHTML = "");
    
    state.warehouses.forEach(w => {
        const opt = `<option value="${w.id}">${w.name}</option>`;
        w1.innerHTML += opt;
        w2.innerHTML += opt;
        w3.innerHTML += opt;
        w4.innerHTML += opt;
        w5.innerHTML += opt;
    });
}

async function fetchCustomers() {
    const res = await fetch(`${API_URL}/api/customers`);
    state.customers = await res.json();
    renderCustomers(state.customers);
    
    // Populate select
    const select = document.getElementById("c-customer");
    select.innerHTML = '<option value="">— Mijozsiz (Oddiy xarid) —</option>';
    state.customers.forEach(c => {
        select.innerHTML += `<option value="${c.id}">${c.name} (${c.balance.toLocaleString()} UZS)</option>`;
    });
}

async function fetchTransactionsHistory() {
    const res = await fetch(`${API_URL}/api/products`); // Temporary get transactions from endpoint
    // We create a history call
    const txRes = await fetch(`${API_URL}/api/export/excel`); // Excel downloads, we will render it.
    // Fetch transaction list from transactions query
    // Let's create an endpoint in server.py.
    // Wait, let's write a simple helper to load transactions from DB.
    // Let's mock the list using products/history for simplicity or add the endpoint `/api/transactions`
    const txHistoryRes = await fetch(`${API_URL}/api/dashboard/chart`); // Using chart endpoint or creating list
    // Wait, we didn't add `/api/transactions` GET endpoint in server.py! 
    // Let's create it in server.py, or we can fetch products and aggregate transactions history.
    // Let's look at what endpoints are available: we have `/api/transactions` POST.
    // Let's call `/api/transactions` as GET? No, it doesn't exist yet, we'll write a GET handler. Let's make it fetch from database dynamically.
}

// We'll write the API to get transactions, but for now we'll write the render.
function renderHistory(txs) {
    const tbody = document.getElementById("transaction-history-body");
    tbody.innerHTML = "";
    
    if (!txs || txs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-slate-500 italic py-4">Tarixda amallar topilmadi.</td></tr>';
        return;
    }
    
    txs.forEach(t => {
        let typeBadge = "";
        if (t.type === "Kirim") typeBadge = '<span class="text-emerald-500 font-bold">Kirim</span>';
        else if (t.type === "Chiqim") typeBadge = '<span class="text-red-500 font-bold">Chiqim</span>';
        else if (t.type === "Transfer") typeBadge = '<span class="text-blue-400 font-bold">Transfer</span>';
        else if (t.type === "Spisat") typeBadge = '<span class="text-amber-500 font-bold">Spisat</span>';
        
        tbody.innerHTML += `
            <tr>
                <td class="whitespace-nowrap">${t.created_at}</td>
                <td class="font-semibold">${t.product_name}</td>
                <td>${typeBadge}</td>
                <td class="text-right">${t.quantity}</td>
                <td>${t.warehouse_name}</td>
                <td class="text-right">${t.total_price.toLocaleString()} UZS</td>
                <td>${t.customer_name || t.operator_name || "Tizim"}</td>
            </tr>
        `;
    });
}

// Let's fetch the actual transactions history list from backend
async function fetchTransactionsHistory() {
    try {
        const res = await fetch(`${API_URL}/api/transactions`);
        if (res.ok) {
            const txs = await res.json();
            renderHistory(txs);
        } else {
            // If endpoint doesn't exist, we fall back gracefully
            renderHistory([]);
        }
    } catch (e) {
        console.warn("Transactions GET not available or network error", e);
        renderHistory([]);
    }
}


// --- POPULATE DROPDOWNS ---
function populateProductDropdowns() {
    const kSelect = document.getElementById("k-product");
    const cSelect = document.getElementById("c-product");
    const tSelect = document.getElementById("t-product");
    
    [kSelect, cSelect, tSelect].forEach(s => s.innerHTML = "");
    
    state.products.forEach(p => {
        const opt = `<option value="${p.id}">${p.name} (${p.barcode})</option>`;
        kSelect.innerHTML += opt;
        cSelect.innerHTML += opt;
        tSelect.innerHTML += opt;
    });
    
    // Trigger limits update
    updateChiqimMaxLimit();
    updateTransferMaxLimit();
}

// --- MAX LIMIT UPDATERS FOR FORM MODALS ---
window.updateChiqimMaxLimit = function() {
    const prodId = document.getElementById("c-product").value;
    const whId = document.getElementById("c-warehouse").value;
    if (!prodId || !whId) return;
    
    const prod = state.products.find(p => p.id === parseInt(prodId));
    if (prod) {
        const stock = prod.stocks.find(s => s.warehouse_id === parseInt(whId));
        const qty = stock ? stock.quantity : 0;
        document.getElementById("c-stock-limit").innerText = `Ombordagi joriy qoldiq: ${qty} qop/metr/dona`;
        document.getElementById("c-qty").max = qty;
    }
};

window.updateTransferMaxLimit = function() {
    const prodId = document.getElementById("t-product").value;
    const whId = document.getElementById("t-src-warehouse").value;
    if (!prodId || !whId) return;
    
    const prod = state.products.find(p => p.id === parseInt(prodId));
    if (prod) {
        const stock = prod.stocks.find(s => s.warehouse_id === parseInt(whId));
        const qty = stock ? stock.quantity : 0;
        document.getElementById("t-stock-limit").innerText = `Ombordagi joriy qoldiq: ${qty} qop/metr/dona`;
        document.getElementById("t-qty").max = qty;
    }
};

window.toggleCustomerSelect = function() {
    const type = document.getElementById("c-type").value;
    const group = document.getElementById("c-customer-group");
    if (type === "Chiqim") {
        group.style.display = "block";
    } else {
        group.style.display = "none";
    }
};

// --- RENDER FUNCTIONS ---
function renderProducts(list) {
    const tbody = document.getElementById("stock-table-body");
    tbody.innerHTML = "";
    
    if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-slate-500 italic py-4">Mahsulot topilmadi.</td></tr>';
        return;
    }
    
    const isAdmin = state.currentUser?.role === "Admin";
    const table = document.getElementById("stock-table-element");
    if (table) {
        const costTh = table.querySelector("thead th:nth-child(4)");
        if (costTh) costTh.style.display = isAdmin ? "" : "none";
    }
    
    list.forEach(p => {
        // Aggregate stocks
        p.stocks.forEach(st => {
            const isWarning = st.quantity <= p.min_threshold;
            const statusBadge = isWarning 
                ? '<span class="badge warning">⚠️ Kam qoldi!</span>' 
                : '<span class="badge normal">Normal</span>';
                
            const costTd = isAdmin 
                ? `<td class="text-right text-slate-400 font-mono">${p.cost_price.toLocaleString()}</td>` 
                : "";
                
            tbody.innerHTML += `
                <tr class="${isWarning ? 'bg-red-500/5' : ''}">
                    <td class="font-semibold">
                        <div class="text-slate-100">${p.name}</div>
                        <div class="text-xs text-slate-400 font-mono">${p.barcode}</div>
                    </td>
                    <td><span class="text-slate-300 text-xs">${p.category_name}</span></td>
                    <td>
                        <span class="font-bold text-slate-100">${st.quantity}</span>
                        <div class="text-xs text-slate-400">${st.warehouse_name}</div>
                    </td>
                    ${costTd}
                    <td class="text-right text-emerald-400 font-bold font-mono">${p.selling_price.toLocaleString()}</td>
                    <td>${statusBadge}</td>
                </tr>
            `;
        });
    });
}

function renderCustomers(list) {
    const container = document.getElementById("customers-list-container");
    container.innerHTML = "";
    
    if (list.length === 0) {
        container.innerHTML = '<div class="col-span-2 text-center text-slate-500 italic py-4">Ustalar topilmadi.</div>';
        return;
    }
    
    list.forEach(c => {
        const isDebt = c.balance < 0;
        const balClass = isDebt ? "text-red-500" : (c.balance > 0 ? "text-emerald-500" : "text-slate-400");
        const statusBadge = isDebt 
            ? `<span class="bg-red-500/10 text-red-500 border border-red-500/20 text-xs px-2 py-0.5 rounded font-semibold">Qarzdor</span>` 
            : `<span class="bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 text-xs px-2 py-0.5 rounded font-semibold">Muvozanat</span>`;
            
        container.innerHTML += `
            <div class="glass-panel cursor-pointer flex flex-col justify-between transition-all hover:border-slate-700/60" onclick="toggleCustomerLedger(${c.id}, this)">
                <div class="p-4 flex flex-col gap-3">
                    <div class="flex justify-between items-start">
                        <div>
                            <h4 class="font-bold text-slate-100">${c.name}</h4>
                            <p class="text-xs text-slate-400"><i class="fa-solid fa-phone text-slate-500 mr-1"></i>${c.phone || "—"}</p>
                        </div>
                        ${statusBadge}
                    </div>
                    <div class="flex justify-between items-center border-t border-slate-800 pt-3">
                        <span class="text-xs text-slate-400">Joriy Balans:</span>
                        <span class="font-bold font-mono ${balClass}">${c.balance.toLocaleString()} UZS</span>
                    </div>
                </div>
                <!-- Accordion content for ledger -->
                <div id="customer-ledger-${c.id}" class="customer-accordion-content" onclick="event.stopPropagation()">
                    <div class="text-[10px] font-bold text-slate-400 mb-2 border-b border-slate-800 pb-1 uppercase tracking-wider"><i class="fa-solid fa-file-invoice-dollar mr-1"></i>Xaridlar Ledger Tarixi</div>
                    <div class="ledger-table-container">
                        <table class="ledger-table">
                            <thead>
                                <tr>
                                    <th>Sana</th>
                                    <th>Mahsulot</th>
                                    <th>Miqdor</th>
                                    <th>Summa</th>
                                </tr>
                            </thead>
                            <tbody id="ledger-body-${c.id}">
                                <tr><td colspan="4" class="text-center py-2 text-slate-500 italic">Yuklanmoqda...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;
    });
}

window.toggleCustomerLedger = async function(customerId, element) {
    const content = document.getElementById(`customer-ledger-${customerId}`);
    if (!content) return;
    
    const isActive = content.classList.contains("active");
    
    // Close other active customer accordions
    document.querySelectorAll(".customer-accordion-content").forEach(el => {
        if (el.id !== `customer-ledger-${customerId}`) {
            el.classList.remove("active");
        }
    });
    
    if (isActive) {
        content.classList.remove("active");
    } else {
        content.classList.add("active");
        
        // Fetch ledger history if online
        if (state.isOnline) {
            try {
                const res = await fetch(`${API_URL}/api/customers/${customerId}/history`);
                const history = await res.json();
                renderCustomerLedger(customerId, history);
            } catch (e) {
                console.error("Ledger error:", e);
                renderCustomerLedger(customerId, []);
            }
        } else {
            const tbody = document.getElementById(`ledger-body-${customerId}`);
            tbody.innerHTML = '<tr><td colspan="4" class="text-center py-2 text-slate-500 italic text-[10px]">Oflayn rejimda yuklab bo\'lmaydi.</td></tr>';
        }
    }
    
    if (tg) tg.HapticFeedback.impactOccurred("light");
};

function renderCustomerLedger(customerId, history) {
    const tbody = document.getElementById(`ledger-body-${customerId}`);
    if (!tbody) return;
    tbody.innerHTML = "";
    
    if (!history || history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center py-2 text-slate-500 italic">Xaridlar topilmadi.</td></tr>';
        return;
    }
    
    history.forEach(h => {
        const dateStr = new Date(h.created_at).toLocaleDateString("uz-UZ", {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
        tbody.innerHTML += `
            <tr>
                <td class="text-slate-400 font-mono">${dateStr}</td>
                <td class="font-semibold text-slate-200">${h.product_name}</td>
                <td class="font-mono">${h.quantity} ta</td>
                <td class="text-right font-mono font-bold text-slate-300">${h.total_price.toLocaleString()} UZS</td>
            </tr>
        `;
    });
}

function checkLowStockLevels() {
    const alertsContainer = document.getElementById("low-stock-notifications");
    alertsContainer.innerHTML = "";
    
    let alertCount = 0;
    
    state.products.forEach(p => {
        p.stocks.forEach(st => {
            if (st.quantity <= p.min_threshold) {
                alertCount++;
                alertsContainer.innerHTML += `
                    <div class="flex items-center justify-between bg-red-500/10 border border-red-500/20 rounded-lg p-2 text-red-400">
                        <span>⚠️ <strong>${p.name}</strong> tugamoqda (Qoldiq: ${st.quantity} ta - ${st.warehouse_name})</span>
                        <span class="font-bold">Kam qoldi!</span>
                    </div>
                `;
            }
        });
    });
    
    if (alertCount === 0) {
        alertsContainer.innerHTML = '<div class="text-slate-400 italic">Hozircha barcha mahsulotlar yetarli miqdorda.</div>';
    }
}

// --- CHART RENDERING ---
function renderChart(chartData) {
    const ctx = document.getElementById("turnoverChart").getContext("2d");
    
    const labels = chartData.map(d => d.date);
    const kirimData = chartData.map(d => d.kirim);
    const chiqimData = chartData.map(d => d.chiqim);
    
    if (turnoverChartInstance) {
        turnoverChartInstance.destroy();
    }
    
    turnoverChartInstance = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Kirim (UZS)",
                    data: kirimData,
                    borderColor: "#10B981",
                    backgroundColor: "rgba(16, 185, 129, 0.1)",
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                },
                {
                    label: "Chiqim (UZS)",
                    data: chiqimData,
                    borderColor: "#EF4444",
                    backgroundColor: "rgba(239, 68, 68, 0.1)",
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: "#94A3B8",
                        font: { family: "Plus Jakarta Sans", size: 10 }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: "rgba(255,255,255,0.03)" },
                    ticks: { color: "#94A3B8" }
                },
                y: {
                    grid: { color: "rgba(255,255,255,0.03)" },
                    ticks: {
                        color: "#94A3B8",
                        callback: function(value) {
                            return value >= 1000000 
                                ? (value / 1000000) + "M" 
                                : (value / 1000) + "k";
                        }
                    }
                }
            }
        }
    });
}

// --- MODAL CONTROLS ---
window.openModal = function(modalId) {
    document.getElementById(modalId).classList.add("active");
};

window.closeModal = function(modalId) {
    document.getElementById(modalId).classList.remove("active");
};

// --- FORM SUBMISSION HANDLERS ---

// 1. Yangi mahsulot qo'shish
window.handleNewProduct = async function(event) {
    event.preventDefault();
    
    const payload = {
        barcode: document.getElementById("p-barcode").value,
        name: document.getElementById("p-name").value,
        category_id: parseInt(document.getElementById("p-category").value),
        cost_price: parseFloat(document.getElementById("p-cost").value),
        selling_price: parseFloat(document.getElementById("p-price").value),
        min_threshold: parseFloat(document.getElementById("p-min").value),
        warehouse_id: parseInt(document.getElementById("p-warehouse").value),
        initial_stock: parseFloat(document.getElementById("p-stock").value)
    };
    
    if (!state.isOnline) {
        showToast("Oflayn rejimda yangi mahsulot yaratib bo'lmaydi!", "error");
        return;
    }
    
    try {
        const res = await fetch(`${API_URL}/api/products`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        const data = await res.json();
        if (res.ok) {
            showToast("Mahsulot muvaffaqiyatli saqlandi!", "success");
            closeModal("modal-new-product");
            document.getElementById("form-new-product").reset();
            loadAllData();
            if (tg) tg.HapticFeedback.notificationOccurred("success");
        } else {
            showToast(data.detail || "Xatolik yuz berdi.", "error");
        }
    } catch (e) {
        showToast("Server bilan bog'lanishda xato.", "error");
    }
};

// 2. Skladga Kirim
window.handleKirim = async function(event) {
    event.preventDefault();
    
    const payload = {
        product_id: parseInt(document.getElementById("k-product").value),
        warehouse_id: parseInt(document.getElementById("k-warehouse").value),
        type: "Kirim",
        quantity: parseFloat(document.getElementById("k-qty").value),
        user_id: tg?.initDataUnsafe?.user?.id || 99999999
    };
    
    if (!state.isOnline) {
        queueOfflineTransaction(payload);
        closeModal("modal-kirim");
        document.getElementById("form-kirim").reset();
        return;
    }
    
    try {
        const res = await fetch(`${API_URL}/api/transactions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (res.ok) {
            showToast("Skladga kirim muvaffaqiyatli bajarildi!", "success");
            closeModal("modal-kirim");
            document.getElementById("form-kirim").reset();
            loadAllData();
            if (tg) tg.HapticFeedback.notificationOccurred("success");
        } else {
            const data = await res.json();
            showToast(data.detail || "Xatolik yuz berdi.", "error");
        }
    } catch (e) {
        showToast("Server bilan ulanish xatosi.", "error");
    }
};

// 3. Chiqim qilish
window.handleChiqim = async function(event) {
    event.preventDefault();
    
    const custId = document.getElementById("c-customer").value;
    const payload = {
        product_id: parseInt(document.getElementById("c-product").value),
        warehouse_id: parseInt(document.getElementById("c-warehouse").value),
        type: document.getElementById("c-type").value,
        quantity: parseFloat(document.getElementById("c-qty").value),
        customer_id: custId ? parseInt(custId) : null,
        user_id: tg?.initDataUnsafe?.user?.id || 99999999
    };
    
    if (!state.isOnline) {
        queueOfflineTransaction(payload);
        closeModal("modal-chiqim");
        document.getElementById("form-chiqim").reset();
        return;
    }
    
    try {
        const res = await fetch(`${API_URL}/api/transactions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (res.ok) {
            showToast("Chiqim operatsiyasi yakunlandi!", "success");
            closeModal("modal-chiqim");
            document.getElementById("form-chiqim").reset();
            loadAllData();
            if (tg) tg.HapticFeedback.notificationOccurred("success");
        } else {
            const data = await res.json();
            showToast(data.detail || "Xatolik yuz berdi.", "error");
        }
    } catch (e) {
        showToast("Server bilan ulanish xatosi.", "error");
    }
};

// 4. Transfer qilish
window.handleTransfer = async function(event) {
    event.preventDefault();
    
    const src = parseInt(document.getElementById("t-src-warehouse").value);
    const dst = parseInt(document.getElementById("t-dst-warehouse").value);
    
    if (src === dst) {
        showToast("Yuboruvchi va qabul qiluvchi ombor bir xil bo'lishi mumkin emas!", "error");
        return;
    }
    
    const payload = {
        product_id: parseInt(document.getElementById("t-product").value),
        warehouse_id: src,
        target_warehouse_id: dst,
        type: "Transfer",
        quantity: parseFloat(document.getElementById("t-qty").value),
        user_id: tg?.initDataUnsafe?.user?.id || 99999999
    };
    
    if (!state.isOnline) {
        queueOfflineTransaction(payload);
        closeModal("modal-transfer");
        document.getElementById("form-transfer").reset();
        return;
    }
    
    try {
        const res = await fetch(`${API_URL}/api/transactions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (res.ok) {
            showToast("Skladlararo transfer muvaffaqiyatli yakunlandi!", "success");
            closeModal("modal-transfer");
            document.getElementById("form-transfer").reset();
            loadAllData();
            if (tg) tg.HapticFeedback.notificationOccurred("success");
        } else {
            const data = await res.json();
            showToast(data.detail || "Xatolik yuz berdi.", "error");
        }
    } catch (e) {
        showToast("Server bilan ulanish xatosi.", "error");
    }
};

// 5. Yangi usta qo'shish
window.handleNewCustomer = async function(event) {
    event.preventDefault();
    
    const payload = {
        name: document.getElementById("cust-name").value,
        phone: document.getElementById("cust-phone").value
    };
    
    if (!state.isOnline) {
        showToast("Oflayn rejimda yangi usta yaratib bo'lmaydi!", "error");
        return;
    }
    
    try {
        const res = await fetch(`${API_URL}/api/customers`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (res.ok) {
            showToast("Usta muvaffaqiyatli qo'shildi!", "success");
            closeModal("modal-new-customer");
            document.getElementById("form-new-customer").reset();
            loadAllData();
            if (tg) tg.HapticFeedback.notificationOccurred("success");
        } else {
            const data = await res.json();
            showToast(data.detail || "Xatolik yuz berdi.", "error");
        }
    } catch (e) {
        showToast("Server bilan ulanish xatosi.", "error");
    }
};

// --- TOAST NOTIFICATIONS ---
function showToast(message, type = "success") {
    const container = document.getElementById("toast-container");
    const icon = document.getElementById("toast-icon");
    const text = document.getElementById("toast-message");
    
    container.className = `toast show ${type}`;
    text.innerText = message;
    
    if (type === "success") {
        icon.innerHTML = '<i class="fa-solid fa-circle-check"></i>';
    } else if (type === "error") {
        icon.innerHTML = '<i class="fa-solid fa-circle-xmark"></i>';
    } else {
        icon.innerHTML = '<i class="fa-solid fa-circle-info"></i>';
    }
    
    setTimeout(() => {
        container.classList.remove("show");
    }, 4000);
}
