/* agent-bulletin · app.js
 * Vanilla JS — no external dependencies.
 */
(function () {
  "use strict";

  const API = {
    REFRESH: "api/refresh.php",
    ANSWER:  "api/answer.php",
    RAW:     "api/raw.php",
  };
  const MANIFEST_URL = "data/manifest.json";
  const POLL_INTERVAL_MS = 15000;   // 後台 polling manifest
  const WAIT_FOR_SYNC_MS = 12000;   // 點擊刷新 / 送出後，等 sync_bulletin 完成

  let manifest = null;
  let pollTimer = null;
  let qaThreadId = null;
  let viewThreadId = null;

  // ────────── helpers ──────────
  const $ = (id) => document.getElementById(id);

  function esc(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    const m = String(iso).match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
    if (m) return `${m[1]} ${m[2]}`;
    return String(iso).slice(0, 16);
  }

  function fmtTo(toVal) {
    if (Array.isArray(toVal)) return toVal.join(" / ");
    if (toVal == null) return "—";
    return String(toVal);
  }

  async function fetchJSON(url, opts = {}) {
    const r = await fetch(url, opts);
    let data = null;
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) {
      const msg = (data && (data.error || data.message)) || `http ${r.status}`;
      throw new Error(msg);
    }
    return data;
  }

  async function loadManifest() {
    return await fetchJSON(`${MANIFEST_URL}?t=${Date.now()}`);
  }

  async function waitForNewerManifest(prevGeneratedAt) {
    const deadline = Date.now() + WAIT_FOR_SYNC_MS;
    let last = null;
    while (Date.now() < deadline) {
      await new Promise((s) => setTimeout(s, 1500));
      try {
        last = await loadManifest();
        if (last.generated_at > prevGeneratedAt) return last;
      } catch (_) { /* retry */ }
    }
    return last || manifest;  // 逾時回原 manifest
  }

  function findThread(tid) {
    if (!manifest) return null;
    for (const k of ["in_progress", "paused", "closed"]) {
      const list = manifest.groups[k] || [];
      const f = list.find((t) => t.thread_id === tid);
      if (f) return f;
    }
    return null;
  }

  // ────────── table rendering ──────────
  function rowHTML(t) {
    const status = esc(t.status || "—");
    const prio = esc(t.priority || "normal");
    const qaFlag = t.flag_awaiting_decision
      ? ` <span class="qa-flag">待回覆</span>` : "";
    const subj = esc(t.subject || "(無標題)");
    const initiator = esc(t.initiator || "—");
    const to = esc(fmtTo(t.to));
    const tid = encodeURIComponent(t.thread_id);
    const qaBtn = t.flag_awaiting_decision
      ? ` <button class="btn qa-open" data-tid="${t.thread_id}">Q&amp;A</button>` : "";
    return `<tr>
      <td>${fmtTime(t.created)}</td>
      <td>${initiator}</td>
      <td>${to}</td>
      <td><span class="status-tag ${status}">${status}</span></td>
      <td><span class="priority ${prio}">${prio}</span></td>
      <td class="subject-cell">${subj}${qaFlag}</td>
      <td>
        <a href="view.html?id=${tid}" target="_blank">檢視</a>${qaBtn}
      </td>
    </tr>`;
  }

  function closedRowHTML(t) {
    const status = esc(t.status || "—");
    const subj = esc(t.subject || "(無標題)");
    const initiator = esc(t.initiator || "—");
    const to = esc(fmtTo(t.to));
    const tid = encodeURIComponent(t.thread_id);
    return `<tr>
      <td>${fmtTime(t.created)}</td>
      <td>${initiator}</td>
      <td>${to}</td>
      <td><span class="status-tag ${status}">${status}</span></td>
      <td>${fmtTime(t.last_action_at || t.created)}</td>
      <td class="subject-cell">${subj}</td>
      <td><a href="view.html?id=${tid}" target="_blank">檢視</a></td>
    </tr>`;
  }

  function pendingRowHTML(t) {
    const subj = esc(t.subject || "(無標題)");
    const initiator = esc(t.initiator || "—");
    const to = esc(fmtTo(t.to));
    const tid = encodeURIComponent(t.thread_id);
    return `<tr>
      <td>${fmtTime(t.created)}</td>
      <td>${initiator}</td>
      <td>${to}</td>
      <td class="subject-cell">${subj}</td>
      <td>
        <a href="view.html?id=${tid}" target="_blank">檢視</a>
        <button class="btn qa-open" data-tid="${t.thread_id}">Q&amp;A</button>
      </td>
    </tr>`;
  }

  function render(m) {
    manifest = m;
    const c = m.counts || {};
    $("cnt-in_progress").textContent = c.in_progress ?? "?";
    $("cnt-paused").textContent      = c.paused ?? "?";
    $("cnt-closed").textContent      = c.closed ?? "?";

    const pendingMaster = m.pending_for_master || [];
    $("cnt-pending_master").textContent = pendingMaster.length;
    $("cnt-pending_master").classList.toggle("warn", pendingMaster.length > 0);

    const tbodyIP = $("tbody-in_progress");
    tbodyIP.innerHTML = (m.groups.in_progress || []).length === 0
      ? `<tr><td colspan="7" class="empty">沒有進行中的 thread</td></tr>`
      : m.groups.in_progress.map(rowHTML).join("");

    const tbodyPA = $("tbody-paused");
    tbodyPA.innerHTML = (m.groups.paused || []).length === 0
      ? `<tr><td colspan="7" class="empty">沒有暫停的 thread</td></tr>`
      : m.groups.paused.map(rowHTML).join("");

    const tbodyCL = $("tbody-closed");
    tbodyCL.innerHTML = (m.groups.closed || []).length === 0
      ? `<tr><td colspan="7" class="empty">沒有結案的 thread</td></tr>`
      : m.groups.closed.map(closedRowHTML).join("");

    const tbodyPENM = $("tbody-pending_master");
    if (pendingMaster.length === 0) {
      tbodyPENM.innerHTML = `<tr><td colspan="5" class="empty">沒有待主人回覆的 thread</td></tr>`;
    } else {
      const allThreads = [].concat(
        m.groups.in_progress || [],
        m.groups.paused || [],
        m.groups.closed || []
      );
      const map = new Map(allThreads.map((t) => [t.thread_id, t]));
      const list = pendingMaster.map((id) => map.get(id)).filter(Boolean);
      tbodyPENM.innerHTML = list.map(pendingRowHTML).join("");
    }

    $("last-sync").textContent = `最後同步 ${fmtTime(m.generated_at)}`;
    bindQaButtons();
  }

  function bindQaButtons() {
    document.querySelectorAll(".qa-open").forEach((b) => {
      b.onclick = () => openQaModal(b.dataset.tid);
    });
  }

  // ────────── tabs ──────────
  function switchTab(name) {
    document.querySelectorAll(".tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === name);
    });
    document.querySelectorAll(".panel").forEach((p) => {
      p.classList.toggle("active", p.id === `panel-${name}`);
    });
  }

  // ────────── refresh ──────────
  async function onRefresh() {
    const btn = $("refresh-btn");
    const st  = $("refresh-status");
    btn.disabled = true;
    st.className = "status working";
    st.textContent = "同步中…";
    try {
      await fetchJSON(API.REFRESH, { method: "POST" });
      const updated = await waitForNewerManifest(manifest ? manifest.generated_at : "");
      render(updated);
      st.className = "status ok";
      st.textContent = "✓ 已同步";
    } catch (e) {
      st.className = "status fail";
      st.textContent = "✗ " + (e.message || "fail");
    } finally {
      btn.disabled = false;
      setTimeout(() => { st.textContent = "—"; st.className = "status"; }, 4000);
    }
  }

  // ────────── Q&A modal ──────────
  async function openQaModal(threadId) {
    qaThreadId = threadId;
    const t = findThread(threadId);
    if (!t) { alert("找不到 thread: " + threadId); return; }
    $("qa-title").textContent = `Q&A · ${t.subject || threadId}`;
    $("qa-thread-info").innerHTML =
      `<strong>thread_id:</strong> <code>${esc(threadId)}</code><br>` +
      `<strong>發起人:</strong> ${esc(t.initiator)} → <strong>對象:</strong> ${esc(fmtTo(t.to))}<br>` +
      `<strong>狀態:</strong> <span class="status-tag ${esc(t.status)}">${esc(t.status)}</span> ` +
      `· <strong>優先:</strong> ${esc(t.priority || "normal")}`;
    try {
      const r = await fetch(`${API.RAW}?id=${encodeURIComponent(threadId)}`);
      const md = await r.text();
      const tail = (md || "").split("\n").slice(-30).join("\n");
      $("qa-history").textContent = tail;
    } catch (_) {
      $("qa-history").textContent = "(無法載入歷史)";
    }
    $("qa-text").value = "";
    $("qa-action").value = "answer";
    $("qa-decision").value = "";
    $("qa-modal").classList.remove("hidden");
    setTimeout(() => $("qa-text").focus(), 50);
  }

  async function submitQa(e) {
    if (e) e.preventDefault();
    if (!qaThreadId) return;
    const text = $("qa-text").value.trim();
    if (!text) { alert("內容不能空白"); return; }
    const action = $("qa-action").value;
    const decision = $("qa-decision").value || null;
    const payload = { thread_id: qaThreadId, action, decision, text };
    const btn = $("qa-submit");
    btn.disabled = true;
    $("refresh-status").textContent = "送出 → 等 warden 寫回…";
    $("refresh-status").className  = "status working";
    try {
      await fetchJSON(API.ANSWER, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      $("qa-modal").classList.add("hidden");
      const updated = await waitForNewerManifest(manifest ? manifest.generated_at : "");
      render(updated);
      $("refresh-status").textContent = "✓ 已寫回 thread";
      $("refresh-status").className  = "status ok";
      setTimeout(() => { $("refresh-status").textContent = "—"; $("refresh-status").className = "status"; }, 4000);
    } catch (err) {
      alert("送出失敗: " + err.message);
      $("refresh-status").textContent = "✗ " + err.message;
      $("refresh-status").className  = "status fail";
    } finally {
      btn.disabled = false;
    }
  }

  // ────────── view.html init ──────────
  async function viewInit() {
    const params = new URLSearchParams(location.search);
    const tid = params.get("id");
    if (!tid) {
      $("v-body").textContent = "missing ?id";
      return;
    }
    viewThreadId = tid;

    // 先 load 一次 manifest(跟 index.html 一樣,某些 header/pending 區可能需要)
    try { manifest = await loadManifest(); } catch (_) {}

    await renderThreadBody(tid);

    const submitBtn = $("vp-submit");
    if (submitBtn) {
      submitBtn.onclick = async () => {
        const text = $("vp-text").value.trim();
        if (!text) { alert("內容不能空白"); return; }
        const action = $("vp-action").value;
        const decision = $("vp-decision").value || null;
        $("vp-status").textContent = "送出中…";
        submitBtn.disabled = true;
        try {
          await fetchJSON(API.ANSWER, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ thread_id: tid, action, decision, text }),
          });
          $("vp-text").value = "";
          // 等 warden 寫回 thread + sync 更新 manifest
          const prevGen = manifest ? manifest.generated_at : "";
          const updated = await waitForNewerManifest(prevGen);
          if (updated) manifest = updated;
          // 重新 fetch raw + 重 render
          await renderThreadBody(tid);
          $("vp-status").textContent = "✓ 已寫入 thread，新內容已顯示";
        } catch (e) {
          $("vp-status").textContent = "✗ " + e.message;
        } finally {
          submitBtn.disabled = false;
        }
      };
    }

    const reloadLink = $("vp-reload");
    if (reloadLink) reloadLink.onclick = (e) => {
      e.preventDefault();
      // hard reload,繞過 HTTP cache;部分瀏覽器對 raw.php 不帶 cache header 仍會 cache
      location.reload();
    };

    // polling:manifest 變更新就重 fetch raw + render(送出後不必手動 F5)
    if (!pollTimer) {
      pollTimer = setInterval(async () => {
        try {
          const m = await loadManifest();
          if (!manifest || m.generated_at > manifest.generated_at) {
            manifest = m;
            await renderThreadBody(tid);
          }
        } catch (_) { /* 忽略,下一輪 */ }
      }, POLL_INTERVAL_MS);
    }
  }

  // ────────── view.html helpers ──────────
  // 注:放在 viewInit 後是 OK 的,function declaration 會 hoist,viewInit 內部
  // await renderThreadBody() 仍可呼叫。這個順序只為了讓 viewInit 主流程先讀完。
  async function loadRaw(threadId) {
    // 加 cache buster,避免 reload() 後 raw.md 被 HTTP cache 撐住
    const r = await fetch(`${API.RAW}?id=${encodeURIComponent(threadId)}&t=${Date.now()}`);
    if (!r.ok) throw new Error("http " + r.status);
    return await r.text();
  }

  async function renderThreadBody(tid) {
    try {
      const md = await loadRaw(tid);
      $("v-body").textContent = md;
      const sub = (md.match(/^subject:\s*(.+)$/m) || [])[1];
      if (sub) $("v-subject").textContent = sub.trim();
      const meta = (md.match(/^---\n([\s\S]*?)\n---/) || [])[1] || "";
      $("v-meta").textContent = meta;
      renderMasterFlagBanner(tid);
    } catch (e) {
      $("v-body").textContent = "load fail: " + e.message;
    }
  }

  function renderMasterFlagBanner(tid) {
    // 移除舊 banner
    const old = document.getElementById("v-master-banner");
    if (old) old.remove();
    if (!manifest) return;
    // 找當前 thread
    const allThreads = [].concat(
      manifest.groups.in_progress || [],
      manifest.groups.paused || [],
      manifest.groups.closed || []
    );
    const t = allThreads.find((x) => x.thread_id === tid);
    if (!t) return;
    if (t.flag_awaiting_master_decision !== "master") return;
    // 加 banner
    const banner = document.createElement("div");
    banner.id = "v-master-banner";
    banner.className = "banner master-flag";
    const reason = (t.flags && t.flags.reason) ? `<br>原因: ${esc(t.flags.reason)}` : "";
    const raisedAt = (t.flags && t.flags["raised-at"]) ? esc(t.flags["raised-at"]) : "—";
    banner.innerHTML = `🎩 此 thread 被 agent escalate(<code>flags.awaiting-master-decision</code>)，等主人決策<br>升起時間: ${raisedAt}${reason}`;
    // 插在 meta 後面
    const meta = $("v-meta");
    if (meta && meta.parentNode) {
      meta.parentNode.insertBefore(banner, meta.nextSibling);
    }
  }

  // ────────── boot ──────────
  function init() {
    if ($("refresh-btn")) $("refresh-btn").onclick = onRefresh;
    document.querySelectorAll(".tab").forEach((b) => {
      b.onclick = () => switchTab(b.dataset.tab);
    });
    document.querySelectorAll("[data-close]").forEach((b) => {
      b.onclick = (e) => {
        e.preventDefault();
        const m = $("qa-modal");
        if (m) m.classList.add("hidden");
      };
    });
    if ($("qa-submit")) $("qa-submit").onclick = submitQa;

    loadManifest()
      .then(render)
      .catch((e) => {
        const tb = $("tbody-in_progress");
        if (tb) tb.innerHTML = `<tr><td colspan="7" class="empty">載入失敗：${esc(e.message)}</td></tr>`;
      });

    pollTimer = setInterval(async () => {
      try {
        const m = await loadManifest();
        if (!manifest || m.generated_at > manifest.generated_at) render(m);
      } catch (_) { /* 忽略，繼續下一輪 */ }
    }, POLL_INTERVAL_MS);
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("refresh-btn")) init();
  });

  // 提供給 view.html 直接呼叫
  window.App = { viewInit };
})();
