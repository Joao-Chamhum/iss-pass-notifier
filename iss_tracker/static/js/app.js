/* ISS Pass Notifier — lógica do dashboard (JavaScript puro). */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const CFG = window.ISS_CONFIG || {};
  const VISIBILITY_RADIUS_M = 1_400_000; // ≈ raio onde a ISS fica ≥ 10° acima do horizonte
  const browserTZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const fmtDate = new Intl.DateTimeFormat("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" });
  const fmtTime = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const fmtShort = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

  const state = { location: null, passes: [], followIss: true, charts: {} };

  // ------------------------------------------------------------------ utils
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (res.status === 204) return null;
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `Erro HTTP ${res.status}`);
    return body;
  }

  function toast(message, variant = "primary") {
    const el = document.createElement("div");
    el.className = `toast align-items-center text-bg-${variant} border-0`;
    el.setAttribute("role", "alert");
    el.innerHTML = `<div class="d-flex"><div class="toast-body">${escapeHtml(message)}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    $("#toast-area").appendChild(el);
    const t = new bootstrap.Toast(el, { delay: 4500 });
    el.addEventListener("hidden.bs.toast", () => el.remove());
    t.show();
  }

  const fmtDuration = (s) => `${Math.floor(s / 60)}min ${String(s % 60).padStart(2, "0")}s`;

  // -------------------------------------------------------------------- mapa
  const map = L.map("map", { worldCopyJump: true, minZoom: 1 }).setView([0, 0], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 8,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const issMarker = L.marker([0, 0], {
    icon: L.icon({ iconUrl: CFG.issIcon, className: "iss-icon", iconSize: [40, 40], iconAnchor: [20, 20] }),
    zIndexOffset: 1000,
  }).addTo(map).bindTooltip("ISS");
  const footprint = L.circle([0, 0], {
    radius: VISIBILITY_RADIUS_M, color: "#0d6efd", weight: 1, fillOpacity: 0.08,
  }).addTo(map);
  const trackLayer = L.layerGroup().addTo(map);
  let userMarker = null;

  /** Divide a trajetória quando cruza o antimeridiano (±180°). */
  function splitSegments(points) {
    const segments = [];
    let current = [];
    points.forEach((p, i) => {
      if (i > 0 && Math.abs(p.lon - points[i - 1].lon) > 180) {
        segments.push(current);
        current = [];
      }
      current.push([p.lat, p.lon]);
    });
    if (current.length) segments.push(current);
    return segments;
  }

  async function loadTrack() {
    try {
      const { points } = await api("/api/iss/track");
      trackLayer.clearLayers();
      const past = points.filter((p) => !p.future);
      const future = points.filter((p) => p.future);
      splitSegments(past).forEach((seg) =>
        L.polyline(seg, { color: "#8a94a6", weight: 2, dashArray: "6 6" }).addTo(trackLayer));
      splitSegments(future).forEach((seg) =>
        L.polyline(seg, { color: "#0d6efd", weight: 3 }).addTo(trackLayer));
    } catch (err) {
      console.warn("Trajetória indisponível:", err);
    }
  }

  async function updatePosition() {
    try {
      const p = await api("/api/iss/now");
      const latlng = [p.latitude, p.longitude];
      issMarker.setLatLng(latlng);
      footprint.setLatLng(latlng);
      if (state.followIss) map.panTo(latlng, { animate: true });
      $("#iss-lat").textContent = `${p.latitude.toFixed(3)}°`;
      $("#iss-lon").textContent = `${p.longitude.toFixed(3)}°`;
      $("#iss-alt").textContent = p.altitude_km ? `${p.altitude_km} km` : "≈ 420 km";
      $("#iss-vel").textContent = p.velocity_kmh
        ? `${Math.round(p.velocity_kmh).toLocaleString("pt-BR")} km/h` : "≈ 27.600 km/h";
      $("#iss-source").textContent = p.source;
      $("#iss-updated").textContent = fmtTime.format(new Date(p.timestamp * 1000));
    } catch (err) {
      $("#iss-source").textContent = `indisponível (${err.message})`;
    }
  }

  map.on("click", (e) => {
    setLocation(e.latlng.lat, e.latlng.wrap().lng, true);
  });
  map.on("dragstart", () => {
    state.followIss = false;
    $("#follow-iss").checked = false;
  });
  $("#follow-iss").addEventListener("change", (e) => { state.followIss = e.target.checked; });

  // -------------------------------------------------------------- localização
  function setLocation(lat, lon, fetchNow = false) {
    lat = Number(lat); lon = Number(lon);
    $("#lat").value = lat.toFixed(4);
    $("#lon").value = lon.toFixed(4);
    state.location = { lat, lon };
    if (userMarker) userMarker.setLatLng([lat, lon]);
    else userMarker = L.marker([lat, lon]).addTo(map).bindTooltip("Você");
    try { localStorage.setItem("iss-location", JSON.stringify(state.location)); } catch (_) { /* ignore */ }
    if (fetchNow) loadPasses();
  }

  $("#btn-geolocate").addEventListener("click", () => {
    if (!navigator.geolocation) return toast("Geolocalização não suportada pelo navegador.", "warning");
    navigator.geolocation.getCurrentPosition(
      (pos) => setLocation(pos.coords.latitude, pos.coords.longitude, true),
      (err) => toast(`Não foi possível obter a localização: ${err.message}`, "warning"),
      { enableHighAccuracy: false, timeout: 10000 },
    );
  });

  document.querySelectorAll(".preset").forEach((btn) =>
    btn.addEventListener("click", () => setLocation(btn.dataset.lat, btn.dataset.lon, true)));

  $("#location-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const lat = parseFloat($("#lat").value);
    const lon = parseFloat($("#lon").value);
    if (Number.isNaN(lat) || Number.isNaN(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      return toast("Informe latitude (−90 a 90) e longitude (−180 a 180) válidas.", "warning");
    }
    setLocation(lat, lon, true);
  });

  // --------------------------------------------------------------- passagens
  async function loadPasses() {
    if (!state.location) return;
    const { lat, lon } = state.location;
    const days = $("#days").value;
    const minEl = $("#min-el").value || 10;
    $("#passes-body").innerHTML =
      `<tr><td colspan="8" class="text-center py-4"><div class="spinner-border spinner-border-sm"></div> Calculando órbita…</td></tr>`;
    try {
      const data = await api(`/api/passes?lat=${lat}&lon=${lon}&days=${days}&min_elevation=${minEl}`);
      state.passes = data.passes;
      renderPasses(data);
      renderElevationChart(data.passes);
    } catch (err) {
      $("#passes-body").innerHTML =
        `<tr><td colspan="8" class="text-center text-danger py-4">${escapeHtml(err.message)}</td></tr>`;
    }
    loadOverhead();
    loadFrequency();
  }

  function renderPasses(data) {
    $("#pass-count").textContent = `${data.count} passagens`;
    $("#pass-visible").textContent = `${data.visible_count} visíveis`;
    if (!data.passes.length) {
      $("#passes-body").innerHTML =
        `<tr><td colspan="8" class="text-center text-secondary py-4">Nenhuma passagem acima de ${data.min_elevation}° no período.</td></tr>`;
      $("#next-pass").classList.add("d-none");
      return;
    }
    $("#passes-body").innerHTML = data.passes.map((p) => {
      const rise = new Date(p.rise_utc), peak = new Date(p.peak_utc), set = new Date(p.set_utc);
      const badge = p.visible
        ? '<span class="badge text-bg-success"><i class="bi bi-eye"></i> Sim</span>'
        : `<span class="badge text-bg-light text-secondary" title="${p.dark_sky ? "ISS na sombra da Terra" : "Céu claro"}">Não</span>`;
      return `<tr class="${p.visible ? "table-success" : ""}">
        <td>${fmtDate.format(rise)}</td>
        <td>${fmtTime.format(rise)}</td>
        <td>${fmtTime.format(peak)}</td>
        <td>${fmtTime.format(set)}</td>
        <td class="text-end fw-semibold">${p.max_elevation}°</td>
        <td class="text-end">${fmtDuration(p.duration_s)}</td>
        <td>${p.rise_direction} → ${p.set_direction}</td>
        <td>${badge}</td>
      </tr>`;
    }).join("");
    $("#next-pass").classList.remove("d-none");
    tickCountdown();
  }

  function tickCountdown() {
    const now = Date.now();
    const next = state.passes.find((p) => new Date(p.set_utc).getTime() > now);
    if (!next) { $("#countdown").textContent = "—"; return; }
    const rise = new Date(next.rise_utc).getTime();
    const diff = Math.max(0, Math.floor((rise - now) / 1000));
    if (diff === 0) {
      $("#countdown").textContent = "Passando agora! 👆";
    } else {
      const h = Math.floor(diff / 3600), m = Math.floor((diff % 3600) / 60), s = diff % 60;
      $("#countdown").textContent = `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
    }
    $("#next-pass-detail").innerHTML =
      `${fmtShort.format(new Date(next.rise_utc))} · elevação máx. <b>${next.max_elevation}°</b> · ` +
      `${next.rise_direction} → ${next.set_direction} · ${next.visible ? "visível a olho nu 👀" : "não visível"}`;
  }
  setInterval(tickCountdown, 1000);

  async function loadOverhead() {
    if (!state.location) return;
    const { lat, lon } = state.location;
    try {
      const d = await api(`/api/overhead?lat=${lat}&lon=${lon}`);
      const icon = (ok) => ok === null
        ? '<i class="bi bi-question-circle text-secondary"></i>'
        : ok ? '<i class="bi bi-check-circle-fill text-success"></i>' : '<i class="bi bi-x-circle text-danger"></i>';
      $("#overhead-box").innerHTML = `
        <li>${icon(d.is_overhead)} ISS a ±5° da sua posição</li>
        <li>${icon(d.is_night)} É noite no local</li>
        <li class="mt-2 fw-semibold">${d.should_notify ? "🔔 Olhe para cima! A ISS está acima de você." : "Nenhum alerta neste momento."}</li>`;
    } catch (err) {
      $("#overhead-box").innerHTML = `<li class="text-danger">${escapeHtml(err.message)}</li>`;
    }
  }

  // ---------------------------------------------------------------- gráficos
  function upsertChart(key, canvas, config) {
    if (state.charts[key]) state.charts[key].destroy();
    state.charts[key] = new Chart(canvas, config);
  }

  async function loadFrequency() {
    const qs = state.location ? `?lat=${state.location.lat}&lon=${state.location.lon}` : "";
    try {
      const data = await api(`/api/stats/frequency${qs}`);
      const locs = data.locations;
      upsertChart("freq", $("#freq-chart"), {
        type: "bar",
        data: {
          labels: locs.map((l) => l.name),
          datasets: [
            { label: "Passagens (≥ 10°)", data: locs.map((l) => l.total), backgroundColor: "rgba(13,110,253,.75)" },
            { label: "Visíveis a olho nu", data: locs.map((l) => l.visible), backgroundColor: "rgba(25,135,84,.8)" },
          ],
        },
        options: {
          maintainAspectRatio: false,
          indexAxis: "y",
          plugins: {
            legend: { position: "bottom" },
            tooltip: { callbacks: { afterBody: (items) => `Melhor elevação: ${locs[items[0].dataIndex].best_elevation}°` } },
          },
          scales: { x: { beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: "nº de passagens" } } },
        },
      });
    } catch (err) {
      console.warn("Frequência indisponível:", err);
    }
  }

  function renderElevationChart(passes) {
    upsertChart("elev", $("#elev-chart"), {
      type: "bar",
      data: {
        labels: passes.map((p) => fmtShort.format(new Date(p.rise_utc))),
        datasets: [{
          label: "Elevação máxima (°)",
          data: passes.map((p) => p.max_elevation),
          backgroundColor: passes.map((p) => (p.visible ? "rgba(25,135,84,.8)" : "rgba(138,148,166,.6)")),
        }],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false },
          tooltip: { callbacks: { afterLabel: (c) => (passes[c.dataIndex].visible ? "Visível a olho nu" : "Não visível") } } },
        scales: { y: { beginAtZero: true, max: 90, title: { display: true, text: "graus acima do horizonte" } } },
      },
    });
  }
  $("#btn-freq").addEventListener("click", loadFrequency);

  // ---------------------------------------------------------------- usuários
  async function loadUsers() {
    const users = await api("/api/users");
    $("#users-body").innerHTML = users.length ? users.map((u) => `
      <tr>
        <td>${escapeHtml(u.name)}</td>
        <td class="small">${escapeHtml(u.email)}</td>
        <td class="small">${u.latitude.toFixed(2)}, ${u.longitude.toFixed(2)}</td>
        <td class="small">
          ${u.notify_passes ? `<span class="badge text-bg-primary pref-badge">${u.lead_minutes} min antes</span>` : ""}
          ${u.notify_overhead ? '<span class="badge text-bg-info pref-badge">Look Up</span>' : ""}
          ${u.only_dark ? '<span class="badge text-bg-dark pref-badge">só visíveis</span>' : ""}
        </td>
        <td class="text-end">
          <div class="form-check form-switch d-inline-block align-middle me-1" title="Ativo">
            <input class="form-check-input toggle-user" type="checkbox" data-id="${u.id}" ${u.active ? "checked" : ""}>
          </div>
          <button class="btn btn-sm btn-outline-danger delete-user" data-id="${u.id}" title="Remover">
            <i class="bi bi-trash"></i>
          </button>
        </td>
      </tr>`).join("")
      : '<tr><td colspan="5" class="text-secondary text-center py-3">Nenhum usuário cadastrado.</td></tr>';
  }

  $("#users-body").addEventListener("click", async (e) => {
    const btn = e.target.closest(".delete-user");
    if (!btn || !confirm("Remover este cadastro?")) return;
    await api(`/api/users/${btn.dataset.id}`, { method: "DELETE" });
    toast("Cadastro removido.", "secondary");
    loadUsers(); loadFrequency();
  });

  $("#users-body").addEventListener("change", async (e) => {
    if (!e.target.classList.contains("toggle-user")) return;
    await api(`/api/users/${e.target.dataset.id}`, {
      method: "PATCH", body: JSON.stringify({ active: e.target.checked }),
    });
    toast(e.target.checked ? "Alertas ativados." : "Alertas pausados.", "secondary");
  });

  $("#user-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.location) return toast("Defina primeiro sua localização (mapa ou formulário).", "warning");
    const payload = {
      name: $("#u-name").value.trim(),
      email: $("#u-email").value.trim() || CFG.defaultEmail,
      latitude: state.location.lat,
      longitude: state.location.lon,
      timezone: $("#u-tz").value.trim(),
      lead_minutes: Number($("#u-lead").value),
      min_elevation: Number($("#min-el").value || 10),
      only_dark: $("#u-dark").checked,
      notify_passes: $("#u-passes").checked,
      notify_overhead: $("#u-overhead").checked,
    };
    try {
      await api("/api/users", { method: "POST", body: JSON.stringify(payload) });
      toast(`Alerta cadastrado para ${payload.email}!`, "success");
      $("#u-name").value = "";
      loadUsers(); loadFrequency();
    } catch (err) {
      toast(err.message, "danger");
    }
  });

  // ---------------------------------------------------------- notificações
  async function loadNotifications() {
    const items = await api("/api/notifications");
    const labels = { pass: "Aviso de passagem", overhead: "Look Up 👆", test: "Teste" };
    $("#notif-list").innerHTML = items.length ? items.map((n) => `
      <li class="list-group-item px-0 d-flex justify-content-between">
        <span>${labels[n.kind] || n.kind} → ${escapeHtml(n.email)}</span>
        <span class="text-secondary">${fmtShort.format(new Date(n.sent_at))}</span>
      </li>`).join("")
      : '<li class="list-group-item px-0 text-secondary">Nenhum e-mail enviado ainda.</li>';
  }

  async function loadStatus() {
    try {
      const s = await api("/api/status");
      const sched = $("#badge-scheduler");
      sched.className = `badge rounded-pill ${s.scheduler_enabled ? "text-bg-success" : "text-bg-warning"}`;
      sched.innerHTML = `<i class="bi bi-clock-history"></i> verificação a cada ${s.check_interval_minutes} min`;
      const mail = $("#badge-email");
      const ok = s.email_configured || s.email_dry_run;
      mail.className = `badge rounded-pill ${ok ? "text-bg-success" : "text-bg-danger"}`;
      mail.innerHTML = `<i class="bi bi-envelope"></i> ${s.email_dry_run ? "e-mail (simulação)" : s.email_configured ? "e-mail configurado" : "SMTP não configurado"}`;
      $("#next-check").textContent = s.next_check ? fmtShort.format(new Date(s.next_check)) : "agendador desativado";
    } catch (_) { /* ignore */ }
  }

  $("#btn-test-email").addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try {
      const r = await api("/api/notify/test", { method: "POST", body: JSON.stringify({ email: CFG.defaultEmail }) });
      toast(`E-mail de teste enviado para ${r.sent_to}${r.dry_run ? " (simulação)" : ""}.`, "success");
    } catch (err) {
      toast(err.message, "danger");
    } finally {
      e.currentTarget.disabled = false;
    }
  });

  $("#btn-check").addEventListener("click", async () => {
    try {
      const r = await api("/api/check", { method: "POST" });
      const msg = r.sent.length ? `${r.sent.length} e-mail(s) enviado(s).` : "Nenhuma passagem na janela de aviso agora.";
      toast(`Verificação concluída: ${msg}`, r.errors.length ? "warning" : "success");
      loadNotifications();
    } catch (err) {
      toast(err.message, "danger");
    }
  });

  // ------------------------------------------------------------- inicializa
  $("#browser-tz").textContent = browserTZ;
  updatePosition();
  loadTrack();
  loadUsers();
  loadNotifications();
  loadStatus();
  loadFrequency();
  setInterval(updatePosition, 5000);
  setInterval(loadTrack, 5 * 60 * 1000);
  setInterval(() => { loadNotifications(); loadStatus(); }, 60 * 1000);

  try {
    const saved = JSON.parse(localStorage.getItem("iss-location") || "null");
    if (saved) setLocation(saved.lat, saved.lon, true);
  } catch (_) { /* ignore */ }
})();
