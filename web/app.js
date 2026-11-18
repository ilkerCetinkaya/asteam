/* Renk Ölçüm Bulutu — web portalı (Supabase veya Demo modu) */
(() => {
  "use strict";
  const cfg = window.RENKOLCUM_CONFIG || {};
  const DEMO = !cfg.SUPABASE_URL || !cfg.SUPABASE_ANON_KEY || new URLSearchParams(location.search).has("demo");
  const WL = Array.from({ length: 39 }, (_, i) => 360 + i * 10);
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v, d = 2) => (v === null || v === undefined ? "–" : Number(v).toFixed(d));
  const fmtDate = (s) => new Date(s).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });
  const ROLE = { admin: "Yönetici", operator: "Operatör", viewer: "İzleyici" };

  // ---------------- Renk dönüşümü (Lab D65 → sRGB) ----------------
  function labToRgb(L, a, b) {
    const fy = (L + 16) / 116, fx = fy + a / 500, fz = fy - b / 200;
    const inv = (t) => (t > 6 / 29 ? t ** 3 : 3 * (6 / 29) ** 2 * (t - 4 / 29));
    const X = inv(fx) * 0.95047, Y = inv(fy), Z = inv(fz) * 1.08883;
    const lin = [3.2406 * X - 1.5372 * Y - 0.4986 * Z, -0.9689 * X + 1.8758 * Y + 0.0415 * Z, 0.0557 * X - 0.204 * Y + 1.057 * Z];
    const g = (c) => { c = Math.min(Math.max(c, 0), 1); return Math.round(255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055)); };
    return `rgb(${lin.map(g).join(",")})`;
  }
  const sw = (o, cls = "") => `<span class="sw ${cls}" style="background:${labToRgb(o.l_star, o.a_star, o.b_star)}"></span>`;

  // ---------------- Veri katmanı ----------------
  function demoApi() {
    const D = structuredClone(window.RENKOLCUM_DEMO);
    let me = D.profiles[0];
    return {
      async signIn(email) { me = D.profiles.find((p) => p.email === email) || D.profiles[0]; return true; },
      async signOut() {}, async hasSession() { return false; },
      async me() { return me; }, async settings() { return D.settings; },
      async profiles() { return D.profiles; }, async standards() { return D.standards; },
      async measurements() { return D.measurements; }, async recipes() { return D.recipes; },
      async setRecipeStatus(id, status) { const r = D.recipes.find((x) => x.id === id); r.status = status; r.version++; },
      async setRole(id, role) { D.profiles.find((x) => x.id === id).role = role; },
      async changePassword() {},
      subscribe(onChange, onStatus) { onStatus(true); },
    };
  }

  function supabaseApi() {
    const sb = window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY);
    const q = async (p) => { const { data, error } = await p; if (error) throw new Error(error.message); return data; };
    let myId = null;
    return {
      async signIn(email, password) {
        const { error } = await sb.auth.signInWithPassword({ email, password });
        if (error) throw new Error(error.message.includes("Invalid") ? "E-posta veya şifre hatalı" : error.message);
      },
      async signOut() { await sb.auth.signOut(); },
      async hasSession() { const { data } = await sb.auth.getSession(); return !!data.session; },
      async me() {
        const { data } = await sb.auth.getUser(); myId = data.user?.id;
        const rows = await q(sb.from("profiles").select("*").eq("id", myId));
        if (!rows.length) throw new Error("Profil bulunamadı (kullanıcı limiti dolmuş olabilir).");
        return rows[0];
      },
      async settings() { return (await q(sb.from("app_settings").select("*")))[0] || { company: "", max_users: 10 }; },
      profiles: () => q(sb.from("profiles").select("*").order("created_at")),
      standards: () => q(sb.from("standards").select("*").order("name")),
      measurements: () => q(sb.from("measurements_view").select("*").order("measured_at", { ascending: false }).limit(500)),
      recipes: () => q(sb.from("recipes_view").select("*").order("created_at", { ascending: false }).limit(500)),
      setRecipeStatus: (id, status) => q(sb.from("recipes").update({ status }).eq("id", id).select()),
      setRole: (id, role) => q(sb.from("profiles").update({ role }).eq("id", id).select()),
      async changePassword(password) { const { error } = await sb.auth.updateUser({ password }); if (error) throw error; },
      subscribe(onChange, onStatus) {
        sb.channel("renkolcum")
          .on("postgres_changes", { event: "*", schema: "public", table: "measurements" }, (p) => onChange("measurements", p))
          .on("postgres_changes", { event: "*", schema: "public", table: "recipes" }, (p) => onChange("recipes", p))
          .on("postgres_changes", { event: "*", schema: "public", table: "standards" }, (p) => onChange("standards", p))
          .subscribe((s) => onStatus(s === "SUBSCRIBED"));
      },
    };
  }

  const api = DEMO ? demoApi() : supabaseApi();
  const state = { me: null, settings: null, profiles: [], standards: [], measurements: [], recipes: [], selected: null };

  // ---------------- UI yardımcıları ----------------
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toast.h); toast.h = setTimeout(() => (t.hidden = true), 3500);
  }
  function chart(series) {
    const W = 340, H = 200, P = { l: 30, r: 8, t: 8, b: 22 };
    const x = (w) => P.l + ((w - 360) / 380) * (W - P.l - P.r);
    const y = (v) => H - P.b - (Math.min(Math.max(v, 0), 100) / 100) * (H - P.t - P.b);
    let g = "";
    for (let v = 0; v <= 100; v += 25) g += `<line class="grid" x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${P.l - 4}" y="${y(v) + 3}" text-anchor="end">${v}</text>`;
    for (let w = 400; w <= 700; w += 100) g += `<text x="${x(w)}" y="${H - 6}" text-anchor="middle">${w}</text>`;
    const path = (r) => r.map((v, i) => `${i ? "L" : "M"}${x(WL[i]).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const lines = series.map((s, i) => `<path class="c${i + 1}" d="${path(s)}"/>`).join("");
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Spektral yansıma eğrisi, 360-740 nm">${g}${lines}</svg>`;
  }

  // ---------------- Render ----------------
  function renderStats() {
    const ms = state.measurements;
    const today = new Date().toDateString();
    const withStd = ms.filter((m) => m.pass_fail);
    const pass = withStd.filter((m) => m.pass_fail === "GEÇTİ").length;
    const avgDe = withStd.length ? withStd.reduce((s, m) => s + m.delta_e2000, 0) / withStd.length : null;
    $("#stats").innerHTML = [
      [ms.length, "Toplam ölçüm"],
      [ms.filter((m) => new Date(m.measured_at).toDateString() === today).length, "Bugün"],
      [withStd.length ? `%${Math.round((100 * pass) / withStd.length)}` : "–", "Geçme oranı"],
      [fmt(avgDe), "Ort. ΔE2000"],
      [state.recipes.length, "Reçete"],
    ].map(([v, l]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");
  }

  function renderMeasurements() {
    const term = $("#m-search").value.toLowerCase(), f = $("#m-filter").value;
    const rows = state.measurements.filter((m) =>
      (!f || m.pass_fail === f) &&
      (!term || [m.sample_name, m.standard_name, m.measured_by_name, m.instrument_serial].join(" ").toLowerCase().includes(term)));
    $("#m-table tbody").innerHTML = rows.map((m) => `<tr data-id="${m.id}" class="${state.selected === m.id ? "sel" : ""}">
      <td>${fmtDate(m.measured_at)}</td><td>${sw(m)}</td><td>${esc(m.sample_name)}</td>
      <td class="num">${fmt(m.l_star)}</td><td class="num">${fmt(m.a_star)}</td><td class="num">${fmt(m.b_star)}</td>
      <td class="num">${fmt(m.delta_e2000)}</td>
      <td>${m.pass_fail ? `<span class="badge ${m.pass_fail === "GEÇTİ" ? "ok" : "bad"}">${m.pass_fail}</span>` : ""}</td>
      <td>${esc(m.measured_by_name)}</td></tr>`).join("") || `<tr><td colspan="9" class="muted">Kayıt yok</td></tr>`;
    renderDetail();
  }

  function renderDetail() {
    const m = state.measurements.find((x) => x.id === state.selected);
    if (!m) return;
    const st = state.standards.find((s) => s.id === m.standard_id);
    const recs = state.recipes.filter((r) => r.measurement_id === m.id);
    $("#m-detail").innerHTML = `
      <h3>${esc(m.sample_name)}</h3>
      <div class="pair"><div>${sw(m, "big")}<small>Numune</small></div>
        ${st ? `<div>${sw(st, "big")}<small>${esc(st.name)}</small></div>` : ""}</div>
      ${chart(st ? [m.reflectance, st.reflectance] : [m.reflectance])}
      <div class="legend"><span><i style="background:var(--curve)"></i>Numune</span>${st ? `<span><i style="background:var(--curve2)"></i>Standart</span>` : ""}<span>% yansıma, 360–740 nm</span></div>
      <dl>
        <dt>L* a* b*</dt><dd>${fmt(m.l_star)} / ${fmt(m.a_star)} / ${fmt(m.b_star)}</dd>
        ${st ? `<dt>ΔE2000</dt><dd>${fmt(m.delta_e2000)} (tol. ${fmt(st.tolerance_de, 1)}) <span class="badge ${m.pass_fail === "GEÇTİ" ? "ok" : "bad"}">${m.pass_fail}</span></dd>` : ""}
        <dt>Cihaz</dt><dd>${esc(m.instrument_model)} · ${esc(m.instrument_serial)}</dd>
        <dt>Ölçen</dt><dd>${esc(m.measured_by_name)}</dd>
        <dt>Tarih</dt><dd>${fmtDate(m.measured_at)}</dd>
        ${recs.map((r) => `<dt>Reçete</dt><dd><div class="comp">${r.components.map((c) => `<span>${esc(c.colorant_code)} %${fmt(c.amount_pct, 3)}</span>`).join("")}</div></dd>`).join("")}
      </dl>`;
  }

  function renderStandards() {
    $("#s-table tbody").innerHTML = state.standards.map((s) => {
      const ms = state.measurements.filter((m) => m.standard_id === s.id);
      const pass = ms.filter((m) => m.pass_fail === "GEÇTİ").length;
      return `<tr><td>${sw(s)}</td><td>${esc(s.name)}</td><td>${esc(s.customer)}</td><td class="num">${fmt(s.l_star)}</td>
        <td class="num">${fmt(s.a_star)}</td><td class="num">${fmt(s.b_star)}</td><td class="num">${fmt(s.tolerance_de, 1)}</td>
        <td class="num">${ms.length}</td><td class="num">${ms.length ? Math.round((100 * pass) / ms.length) : "–"}</td></tr>`;
    }).join("") || `<tr><td colspan="9" class="muted">Standart yok</td></tr>`;
  }

  function renderRecipes() {
    const canEdit = state.me.role === "admin";
    $("#r-table tbody").innerHTML = state.recipes.map((r) => `<tr>
      <td>${fmtDate(r.created_at)}</td><td>${esc(r.name)}<div class="muted small">${esc(r.sample_name || "")}</div></td>
      <td>${esc(r.standard_name || "–")}</td>
      <td><div class="comp">${r.components.map((c) => `<span title="${esc(c.colorant_name)}">${esc(c.colorant_code)} %${fmt(c.amount_pct, 3)}</span>`).join("") || "<span>zemin</span>"}</div></td>
      <td class="num">${fmt(r.predicted_de, 3)}</td>
      <td><span class="badge ${r.status === "onaylı" ? "ok" : r.status === "iptal" ? "bad" : ""}">${esc(r.status)}</span> <span class="muted small">v${r.version}</span></td>
      <td>${esc(r.created_by_name)}</td>
      <td>${canEdit && r.status !== "onaylı" ? `<button class="small" data-approve="${r.id}">Onayla</button>` : ""}</td></tr>`).join("")
      || `<tr><td colspan="8" class="muted">Reçete yok</td></tr>`;
  }

  function renderUsers() {
    const max = state.settings?.max_users ?? 10, isAdmin = state.me.role === "admin";
    $("#seat").textContent = `${state.profiles.length} / ${max}`;
    $("#seat-max").textContent = max;
    $("#u-table tbody").innerHTML = state.profiles.map((p) => `<tr><td>${esc(p.full_name)}</td><td>${esc(p.email)}</td>
      <td>${isAdmin && p.id !== state.me.id
        ? `<select data-role="${p.id}">${Object.entries(ROLE).map(([k, v]) => `<option value="${k}" ${k === p.role ? "selected" : ""}>${v}</option>`).join("")}</select>`
        : `<span class="badge">${ROLE[p.role]}</span>`}</td><td>${fmtDate(p.created_at)}</td></tr>`).join("");
  }

  function renderAll() { renderStats(); renderMeasurements(); renderStandards(); renderRecipes(); renderUsers(); }

  async function load(what = ["profiles", "standards", "measurements", "recipes"]) {
    const res = await Promise.all(what.map((k) => api[k]()));
    what.forEach((k, i) => (state[k] = res[i]));
    if (!state.selected && state.measurements[0]) state.selected = state.measurements[0].id;
    renderAll();
  }

  // ---------------- Akış ----------------
  async function enterApp() {
    state.me = await api.me();
    state.settings = await api.settings();
    $("#login-view").hidden = true; $("#app-view").hidden = false;
    $("#company").textContent = state.settings.company || "Renk Ölçüm Bulutu";
    $("#user-name").textContent = state.me.full_name;
    $("#user-role").textContent = ROLE[state.me.role];
    $("#demo-badge").hidden = !DEMO;
    await load();
    api.subscribe(async (table, p) => {
      await load([table]);
      if (table === "measurements" && p.eventType === "INSERT") toast(`Yeni ölçüm: ${p.new.sample_name}`);
    }, (on) => $("#live").classList.toggle("on", on));
  }

  function showLogin() { $("#app-view").hidden = true; $("#login-view").hidden = false; $("#demo-hint").hidden = !DEMO; }

  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault(); $("#login-error").textContent = "";
    try { await api.signIn($("#login-email").value.trim(), $("#login-password").value); await enterApp(); }
    catch (err) { $("#login-error").textContent = err.message; }
  });
  $("#logout-btn").onclick = async () => { await api.signOut(); location.reload(); };
  $("#pw-btn").onclick = () => $("#pw-dialog").showModal();
  $("#pw-form").addEventListener("submit", async (e) => {
    if (e.submitter?.value !== "ok") return;
    try { await api.changePassword($("#pw-new").value); toast("Şifre güncellendi"); } catch (err) { toast(err.message); }
    $("#pw-new").value = "";
  });
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".tab").forEach((t) => (t.hidden = t.id !== `tab-${b.dataset.tab}`));
  }));
  $("#m-search").oninput = renderMeasurements; $("#m-filter").onchange = renderMeasurements;
  $("#m-table tbody").onclick = (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) { state.selected = tr.dataset.id; renderMeasurements(); } };
  $("#r-table tbody").onclick = async (e) => {
    const id = e.target.dataset.approve; if (!id) return;
    try { await api.setRecipeStatus(id, "onaylı"); await load(["recipes"]); toast("Reçete onaylandı"); } catch (err) { toast(err.message); }
  };
  $("#u-table tbody").onchange = async (e) => {
    const id = e.target.dataset.role; if (!id) return;
    try { await api.setRole(id, e.target.value); await load(["profiles"]); toast("Rol güncellendi"); } catch (err) { toast(err.message); }
  };

  (async () => { if (await api.hasSession()) { try { await enterApp(); return; } catch (e) { console.error(e); } } showLogin(); })();
})();
