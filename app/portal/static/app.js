"use strict";

const CSRF = document.querySelector('meta[name="csrf"]')?.content || "";
const STATUS_LABEL = { queued: "antri", running: "diproses", done: "selesai", failed: "gagal", canceled: "dibatalkan" };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtDuration(sec) {
  if (sec == null) return "";
  sec = Math.max(0, Math.round(sec));
  if (sec < 60) return `${sec} dtk`;
  const m = Math.round(sec / 60);
  return m < 60 ? `${m} mnt` : `${Math.floor(m / 60)} j ${m % 60} mnt`;
}

async function getJSON(url) {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (r.status === 401) { location.href = "/login"; throw new Error("unauthorized"); }
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function poll(fn, ms) {
  let timer = null;
  const tick = async () => {
    try { if (await fn() === false) return; } catch (e) { console.warn(e); }
    timer = setTimeout(tick, document.hidden ? ms * 3 : ms);
  };
  tick();
  return () => clearTimeout(timer);
}

// ---- konfirmasi & prompt untuk form ----
document.addEventListener("submit", (e) => {
  const f = e.target;
  if (f.dataset.confirm && !confirm(f.dataset.confirm)) { e.preventDefault(); return; }
  if (f.dataset.prompt) {
    const v = prompt(f.dataset.prompt, f.dataset.value || "");
    if (v === null || !v.trim()) { e.preventDefault(); return; }
    f.querySelector('input[name="name"]').value = v.trim();
  }
});

// ---- badge antrian di navbar ----
(function queueBadge() {
  const badge = document.getElementById("queue-badge");
  if (!badge) return;
  poll(async () => {
    const s = await getJSON("/api/queue/summary");
    const n = s.running + s.queued;
    badge.hidden = n === 0;
    badge.textContent = n;
    badge.title = `${s.running} diproses, ${s.queued} antri`;
  }, 10000);
})();

// ---- putar audio dari daftar file ----
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-play]");
  if (!btn) return;
  const player = document.getElementById("player");
  player.hidden = false;
  player.src = btn.dataset.play;
  player.play();
});

// ---- upload ----
function initUpload() {
  const input = document.getElementById("file-input");
  const zone = document.getElementById("dropzone");
  const list = document.getElementById("upload-list");
  const queue = [];
  let busy = false;

  const add = (files) => { for (const f of files) queue.push(f); next(); };
  input.addEventListener("change", () => { add(input.files); input.value = ""; });
  ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
  zone.addEventListener("drop", (e) => add(e.dataTransfer.files));

  function next() {
    if (busy) return;
    const file = queue.shift();
    if (!file) return;
    busy = true;
    upload(file).finally(() => { busy = false; next(); });
  }

  function upload(file) {
    const li = document.createElement("li");
    li.innerHTML = `<div class="row"><span>${esc(file.name)}</span><span class="small muted" data-s>0%</span></div><div class="progress"><div style="width:0%"></div></div>`;
    list.prepend(li);
    const bar = li.querySelector(".progress > div");
    const label = li.querySelector("[data-s]");

    const p = new URLSearchParams({ name: file.name });
    const folder = document.getElementById("up-folder").value;
    if (folder) p.set("folder_id", folder);
    if (document.getElementById("up-auto").checked) {
      p.set("auto_job", "1");
      p.set("language", document.getElementById("up-language").value);
      const spk = document.getElementById("up-speaker");
      if (spk.checked) {
        p.set("speaker", "1");
        const mn = document.getElementById("up-min").value, mx = document.getElementById("up-max").value;
        if (mn) p.set("min_speakers", mn);
        if (mx) p.set("max_speakers", mx);
      }
    }

    return new Promise((resolve) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", `/api/files/upload?${p}`);
      xhr.setRequestHeader("X-CSRF-Token", CSRF);
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.setRequestHeader("Accept", "application/json");
      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const pct = Math.round((e.loaded / e.total) * 100);
        bar.style.width = pct + "%";
        label.textContent = pct < 100 ? `${pct}%` : "Memproses di server…";
      };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch (_) {}
        if (xhr.status === 201) {
          bar.style.width = "100%";
          let html = `✔ Tersimpan (${data.storage === "cdn" ? "CDN" : "lokal"})`;
          if (data.job_id) html += ` · <a href="/jobs/${data.job_id}">masuk antrian #${data.job_id}</a>`;
          if (data.job_error) html += ` · <span class="s-failed">${esc(data.job_error)}</span>`;
          label.innerHTML = html;
          scheduleReload();
        } else {
          label.innerHTML = `<span class="s-failed">✖ ${esc(data.detail || xhr.statusText || "Upload gagal")}</span>`;
        }
        resolve();
      };
      xhr.onerror = () => { label.innerHTML = '<span class="s-failed">✖ Koneksi terputus</span>'; resolve(); };
      xhr.send(file);
    });
  }

  let reloadTimer = null;
  function scheduleReload() {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(() => { if (!busy && queue.length === 0) location.reload(); }, 2500);
  }
}

// ---- daftar job (live) ----
function initJobsList() {
  const body = document.getElementById("jobs-body");
  const stats = document.getElementById("queue-stats");
  const paused = document.getElementById("paused-note");
  poll(async () => {
    const data = await getJSON("/api/jobs");
    for (const el of stats.querySelectorAll("[data-k]")) el.textContent = data.summary[el.dataset.k];
    paused.hidden = !data.summary.paused;
    if (!data.jobs.length) {
      body.innerHTML = '<tr><td colspan="6" class="empty">Belum ada job. <a href="/jobs/new">Buat transkripsi</a>.</td></tr>';
      return;
    }
    body.innerHTML = data.jobs.map((j) => {
      let prog = "", eta = "";
      if (j.status === "running") {
        prog = `<div class="progress"><div style="width:${(j.progress * 100).toFixed(1)}%"></div></div><div class="small muted">${esc(j.stage)}</div>`;
        eta = j.eta_sec != null ? `± ${fmtDuration(j.eta_sec)} lagi` : "";
      } else if (j.status === "queued") {
        prog = `<span class="small">Posisi antrian: <b>${j.position ?? "-"}</b></span>`;
        eta = j.eta_sec != null ? `mulai ± ${fmtDuration(j.eta_sec)}` : "";
      } else if (j.status === "failed") {
        prog = `<span class="small s-failed" title="${esc(j.error)}">${esc((j.error || "").slice(0, 80))}</span>`;
      }
      return `<tr>
        <td>${j.id}</td>
        <td><a href="/jobs/${j.id}">${esc(j.title)}</a>${j.speaker ? ' <span class="tag">speaker</span>' : ""}</td>
        <td><span class="status s-${j.status}">${STATUS_LABEL[j.status] || j.status}</span></td>
        <td style="min-width:200px">${prog}</td>
        <td class="small muted">${eta}</td>
        <td class="small">${new Date(j.created_at).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })}</td>
      </tr>`;
    }).join("");
  }, 3000);
}

// ---- detail job ----
function initJobDetail() {
  const live = document.getElementById("live");
  if (live) {
    const f = (k) => live.querySelector(`[data-f="${k}"]`);
    poll(async () => {
      const j = await getJSON(`/api/jobs/${live.dataset.job}`);
      if (!["queued", "running"].includes(j.status)) { location.reload(); return false; }
      f("status").className = `status s-${j.status}`;
      f("status").textContent = STATUS_LABEL[j.status];
      f("bar").style.width = `${(j.progress * 100).toFixed(1)}%`;
      if (j.status === "queued") {
        f("stage").textContent = `Menunggu giliran — posisi antrian ${j.position ?? "-"}`;
        f("eta").textContent = j.eta_sec != null ? `mulai ± ${fmtDuration(j.eta_sec)}` : "";
      } else {
        f("stage").textContent = j.stage || "Memproses…";
        f("eta").textContent = j.eta_sec != null ? `± ${fmtDuration(j.eta_sec)} lagi` : "";
      }
    }, 3000);
  }

  const player = document.getElementById("player");
  const transcript = document.getElementById("transcript");
  if (player && transcript) {
    const segs = [...transcript.querySelectorAll(".seg")];
    transcript.addEventListener("click", (e) => {
      const a = e.target.closest(".ts");
      if (!a) return;
      e.preventDefault();
      player.currentTime = parseFloat(a.closest(".seg").dataset.start);
      player.play();
    });
    player.addEventListener("timeupdate", () => {
      const t = player.currentTime;
      let cur = null;
      for (const s of segs) { if (parseFloat(s.dataset.start) <= t) cur = s; else break; }
      segs.forEach((s) => s.classList.toggle("active", s === cur));
    });
  }

  const copy = document.getElementById("copy-text");
  if (copy && transcript) {
    copy.addEventListener("click", async () => {
      const text = [...transcript.querySelectorAll(".seg")].map((s) => {
        const spk = s.querySelector(".spk");
        return (spk ? `${spk.textContent}: ` : "") + s.querySelector("span").textContent;
      }).join("\n");
      await navigator.clipboard.writeText(text);
      copy.textContent = "Tersalin ✔";
      setTimeout(() => (copy.textContent = "Salin teks"), 1500);
    });
  }
}
