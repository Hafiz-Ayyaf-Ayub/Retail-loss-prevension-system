const statusBadge = document.getElementById("statusBadge");

const personCountEl = document.getElementById("personCount");
const totalCountEl = document.getElementById("totalCount");
const entryCountEl = document.getElementById("entryCount");
const exitCountEl = document.getElementById("exitCount");
const cameraStatusEl = document.getElementById("cameraStatus");

const alertsListEl = document.getElementById("alertsList");
const noAlertsMsgEl = document.getElementById("noAlertsMsg");

const concealListEl = document.getElementById("concealList");
const noConcealMsgEl = document.getElementById("noConcealMsg");

const historyListEl = document.getElementById("historyList");
const noHistoryMsgEl = document.getElementById("noHistoryMsg");

let statsInterval = null;

// Zone on/off state yahan JS mein bhi track karte hain (har camera ke liye
// alag), taake iska button hamesha kaam kare - chahe zone overlay khud
// is waqt "hidden" ho ya visible. (Pehle sirf overlay ke ANDAR wala
// remove-button hi zone wapas ON kar sakta tha, aur woh khud overlay ke
// sath hi ghayab ho jata tha - isliye "wapas on karne" ka koi tareeqa
// nahi bachta tha, sirf server restart hi state reset karta tha.)
const zoneEnabledState = {};

function toggleZone(camId) {
    const key = String(camId);
    const currentlyEnabled = zoneEnabledState[key] !== false; // default: True
    const newEnabled = !currentlyEnabled;
    zoneEnabledState[key] = newEnabled;

    const overlay = document.getElementById(`zoneOverlay${camId}`);
    if (overlay) {
        overlay.classList.toggle("zone-hidden", !newEnabled);
    }

    const zoneBtn = document.querySelector(`.mini-zone[data-cam="${camId}"]`);
    if (zoneBtn) {
        zoneBtn.textContent = newEnabled ? "Zone: On" : "Zone: Off";
        zoneBtn.classList.toggle("zone-off", !newEnabled);
    }

    fetch(`/camera/zone/${camId}/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: newEnabled })
    }).catch(err => console.log(`Camera ${camId} zone toggle failed:`, err));
}

// ---- Per-camera controls ----

function setCamButtons(camId, { startDisabled, pauseDisabled, stopDisabled }) {
    document.querySelector(`.mini-start[data-cam="${camId}"]`).disabled = startDisabled;
    document.querySelector(`.mini-pause[data-cam="${camId}"]`).disabled = pauseDisabled;
    document.querySelector(`.mini-stop[data-cam="${camId}"]`).disabled = stopDisabled;
}

function markCamRunning(camId) {
    const overlay = document.getElementById(`pausedOverlay${camId}`);
    const img = document.getElementById(`videoFeed${camId}`);

    img.src = `/video-feed/${camId}?t=` + new Date().getTime();
    overlay.classList.add("hidden");
    setCamButtons(camId, { startDisabled: true, pauseDisabled: false, stopDisabled: false });

    if (camId === "1" || camId === 1) {
        statusBadge.textContent = "● LIVE";
        statusBadge.className = "status-badge";
    }
    startStatsPolling();
}

function markCamFailed(camId, message) {
    const overlay = document.getElementById(`pausedOverlay${camId}`);
    overlay.querySelector("p").textContent = message;
    overlay.classList.remove("hidden");
}

async function uploadAndStartVideo(camId, file) {
    const overlay = document.getElementById(`pausedOverlay${camId}`);
    overlay.querySelector("p").textContent = "⏳ Uploading video…";
    overlay.classList.remove("hidden");

    const formData = new FormData();
    formData.append("file", file);

    try {
        const response = await fetch(`/camera/upload-video/${camId}?loop=true`, {
            method: "POST",
            body: formData,
        });
        const data = await response.json();

        if (data.status === "started") {
            markCamRunning(camId);
        } else {
            markCamFailed(camId, "⚠ Video Upload Failed");
        }
    } catch (error) {
        console.log(`Camera ${camId} video upload failed:`, error);
        markCamFailed(camId, "⚠ Video Upload Failed");
    }
}

async function startCam(camId) {
    const deviceValue = document.getElementById(`deviceSelect${camId}`).value;

    // ---- "Video File" chuna gaya hai: HAMESHA naya file-picker kholo,
    // koi purani video khud-ba-khud reuse nahi karni (user ne yahi mangi hai) ----
    if (deviceValue === "file") {
        document.getElementById(`videoFileInput${camId}`).click();
        return;
    }

    // ---- Live camera (Laptop / Mobile) ----
    const response = await fetch(`/camera/start/${camId}?device_index=${deviceValue}`, { method: "POST" });
    const data = await response.json();

    if (data.status === "started") {
        markCamRunning(camId);
    } else {
        markCamFailed(camId, "⚠ Camera Not Found");
    }
}

async function pauseCam(camId) {
    await fetch(`/camera/pause/${camId}`, { method: "POST" });
    setCamButtons(camId, { startDisabled: false, pauseDisabled: true, stopDisabled: false });

    if (camId === "1" || camId === 1) {
        statusBadge.textContent = "⏸ PAUSED";
        statusBadge.className = "status-badge paused";
    }
}

async function stopCam(camId) {
    const overlay = document.getElementById(`pausedOverlay${camId}`);
    const img = document.getElementById(`videoFeed${camId}`);

    await fetch(`/camera/stop/${camId}`, { method: "POST" });

    img.src = "";
    overlay.querySelector("p").textContent = "⏹ Feed Stopped";
    overlay.classList.remove("hidden");
    setCamButtons(camId, { startDisabled: false, pauseDisabled: true, stopDisabled: true });

    if (camId === "1" || camId === 1) {
        statusBadge.textContent = "⏹ STOPPED";
        statusBadge.className = "status-badge stopped";
        personCountEl.textContent = "0";
        cameraStatusEl.textContent = "Inactive";
    }
}

document.querySelectorAll(".cam-controls").forEach(panel => {
    panel.addEventListener("click", (e) => {
        e.stopPropagation(); // taake fullscreen toggle na ho jaye button dabane par
        const btn = e.target.closest(".mini-btn");
        if (!btn) return;

        const camId = btn.dataset.cam;
        const action = btn.dataset.action;

        if (action === "start") startCam(camId);
        if (action === "pause") pauseCam(camId);
        if (action === "stop") stopCam(camId);
        if (action === "zone-toggle") toggleZone(camId);
    });
});

// ---- Video-file input: file choose hote hi upload + start ----
document.querySelectorAll("input[type=file][id^='videoFileInput']").forEach(input => {
    input.addEventListener("click", (e) => e.stopPropagation());
    input.addEventListener("change", (e) => {
        const camId = input.id.replace("videoFileInput", "");
        const file = e.target.files[0];
        if (file) {
            uploadAndStartVideo(camId, file);
        }
        input.value = ""; // taake wahi file dobara chuni ja sake to bhi change fire ho
    });
});

// ---- Alerts / History rendering ----

function renderAlerts(alerts) {
    alertsListEl.innerHTML = "";
    if (alerts.length === 0) {
        noAlertsMsgEl.style.display = "block";
        return;
    }
    noAlertsMsgEl.style.display = "none";
    alerts.forEach(alert => {
        const div = document.createElement("div");
        div.className = "alert-item";
        div.textContent = `⚠ ${alert.message}`;
        alertsListEl.appendChild(div);
    });
}

function renderConceal(alerts) {
    concealListEl.innerHTML = "";
    if (alerts.length === 0) {
        noConcealMsgEl.style.display = "block";
        return;
    }
    noConcealMsgEl.style.display = "none";
    alerts.forEach(alert => {
        const div = document.createElement("div");
        div.className = "alert-item";
        div.textContent = alert.message;
        concealListEl.appendChild(div);
    });
}

function renderHistory(history) {
    historyListEl.innerHTML = "";
    if (history.length === 0) {
        noHistoryMsgEl.style.display = "block";
        return;
    }
    noHistoryMsgEl.style.display = "none";
    const reversed = [...history].reverse();
    reversed.forEach(entry => {
        const div = document.createElement("div");
        div.className = "history-item";
        div.innerHTML = `<span>${entry.message}</span><span class="history-time">${entry.time}</span>`;
        historyListEl.appendChild(div);
    });
}

// ---- Stats polling (sab cameras se milakar) ----

async function fetchStats() {
    try {
        const response = await fetch("/stats-all");
        const data = await response.json();

        // Sirf Camera 1 ki analytics sidebar mein dikhayein (jaisa pehle se ho raha tha)
        const cam1 = data.cameras.find(c => c.camera_id === 1);
        if (cam1) {
            personCountEl.textContent = cam1.person_count;
            totalCountEl.textContent = cam1.total_unique_visitors;
            entryCountEl.textContent = cam1.entry_count;
            exitCountEl.textContent = cam1.exit_count;
            cameraStatusEl.textContent = cam1.camera_active ? "Active" : "Inactive";
        }

        // Sab active cameras ke alerts milakar dikhayein, camera number ke sath
        let combinedAlerts = [];
        let combinedConceal = [];

        data.cameras.forEach(cam => {
            (cam.alerts || []).forEach(a => {
                combinedAlerts.push({ message: `[Camera ${cam.camera_id}] ${a.message}` });
            });
            (cam.concealment_alerts || []).forEach(a => {
                combinedConceal.push({ message: `[Camera ${cam.camera_id}] ${a.message}` });
            });
        });

        renderAlerts(combinedAlerts);
        renderConceal(combinedConceal);
        renderHistory([...(data.alert_history || []), ...(data.concealment_history || [])]);
    } catch (error) {
        console.log("Stats fetch failed:", error);
    }
}

function startStatsPolling() {
    if (statsInterval) return; // pehle se chal raha ho to dobara mat shuru karo
    fetchStats();
    statsInterval = setInterval(fetchStats, 1000);
}

function stopStatsPolling() {
    if (statsInterval) {
        clearInterval(statsInterval);
        statsInterval = null;
    }
}

// ---- Adjustable Monitored Zone (drag + resize + remove) ----

function setupZoneOverlay(camId) {
    const overlay = document.getElementById(`zoneOverlay${camId}`);
    if (!overlay) return;

    const wrapper = overlay.closest(".video-wrapper");
    const resizeHandle = overlay.querySelector(".zone-resize");
    const removeBtn = overlay.querySelector(".zone-remove");

    let mode = null; // "drag" ya "resize", warna null
    let startX, startY, startLeft, startTop, startWidth, startHeight;

    function toPercent(px, totalPx) {
        return (px / totalPx) * 100;
    }

    // Zone ke andar click/drag hone se fullscreen mode trigger na ho, isliye click bubble roka
    overlay.addEventListener("click", (e) => e.stopPropagation());

    function sendZoneUpdate() {
        const wrapperRect = wrapper.getBoundingClientRect();
        const x1 = overlay.offsetLeft / wrapperRect.width;
        const y1 = overlay.offsetTop / wrapperRect.height;
        const x2 = (overlay.offsetLeft + overlay.offsetWidth) / wrapperRect.width;
        const y2 = (overlay.offsetTop + overlay.offsetHeight) / wrapperRect.height;

        fetch(`/camera/zone/${camId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ x1, y1, x2, y2 })
        }).catch(err => console.log(`Camera ${camId} zone update failed:`, err));
    }

    overlay.addEventListener("mousedown", (e) => {
        if (e.target === resizeHandle || e.target === removeBtn) return; // wo apna kaam khud karenge
        mode = "drag";
        startX = e.clientX;
        startY = e.clientY;
        startLeft = overlay.offsetLeft;
        startTop = overlay.offsetTop;
        e.preventDefault();
        e.stopPropagation();
    });

    resizeHandle.addEventListener("mousedown", (e) => {
        mode = "resize";
        startX = e.clientX;
        startY = e.clientY;
        startWidth = overlay.offsetWidth;
        startHeight = overlay.offsetHeight;
        e.preventDefault();
        e.stopPropagation();
    });

    removeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleZone(camId); // shared function - dashboard ke persistent button ke sath sync rehta hai
    });

    document.addEventListener("mousemove", (e) => {
        if (!mode) return;
        const wrapperRect = wrapper.getBoundingClientRect();

        if (mode === "drag") {
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            let newLeft = startLeft + dx;
            let newTop = startTop + dy;

            // wrapper ke bahar na jaye
            newLeft = Math.max(0, Math.min(newLeft, wrapperRect.width - overlay.offsetWidth));
            newTop = Math.max(0, Math.min(newTop, wrapperRect.height - overlay.offsetHeight));

            overlay.style.left = toPercent(newLeft, wrapperRect.width) + "%";
            overlay.style.top = toPercent(newTop, wrapperRect.height) + "%";
        }

        if (mode === "resize") {
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            let newWidth = Math.max(30, startWidth + dx);
            let newHeight = Math.max(30, startHeight + dy);

            newWidth = Math.min(newWidth, wrapperRect.width - overlay.offsetLeft);
            newHeight = Math.min(newHeight, wrapperRect.height - overlay.offsetTop);

            overlay.style.width = toPercent(newWidth, wrapperRect.width) + "%";
            overlay.style.height = toPercent(newHeight, wrapperRect.height) + "%";
        }
    });

    document.addEventListener("mouseup", () => {
        if (mode) {
            sendZoneUpdate(); // mouse chhodte hi backend ko naya zone bhej do
        }
        mode = null;
    });
}

["1", "2", "3", "4"].forEach(setupZoneOverlay);

// ---- Multi-camera grid: click to fullscreen ----
const cameraGrid = document.getElementById("cameraGrid");
const closeFullscreenBtn = document.getElementById("closeFullscreenBtn");

if (cameraGrid) {
    cameraGrid.addEventListener("click", (e) => {
        const box = e.target.closest(".camera-box");
        if (!box) return;
        cameraGrid.classList.add("fullscreen-mode");
        cameraGrid.querySelectorAll(".camera-box").forEach(b => b.classList.remove("is-fullscreen"));
        box.classList.add("is-fullscreen");
        closeFullscreenBtn.classList.remove("hidden");
    });
}

if (closeFullscreenBtn) {
    closeFullscreenBtn.addEventListener("click", () => {
        cameraGrid.classList.remove("fullscreen-mode");
        cameraGrid.querySelectorAll(".camera-box").forEach(b => b.classList.remove("is-fullscreen"));
        closeFullscreenBtn.classList.add("hidden");
    });
}