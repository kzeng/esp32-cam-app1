"use strict";
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const localTime = new Intl.DateTimeFormat("zh-CN", {dateStyle: "medium", timeStyle: "medium"});
let toastTimer;

document.querySelectorAll("time.local-time").forEach((node) => {
  const date = new Date(node.dateTime);
  if (!Number.isNaN(date.valueOf())) node.textContent = localTime.format(date);
});

function toast(message) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 4500);
}

document.querySelectorAll("details").forEach((details) => details.addEventListener("toggle", () => {
  if (!details.open) return;
  details.querySelectorAll("img[data-src]").forEach((image) => {
    image.src = image.dataset.src;
    image.removeAttribute("data-src");
  });
}));

const checkboxes = () => Array.from(document.querySelectorAll(".event-checkbox"));
const selectedIds = () => checkboxes().filter((box) => box.checked).map((box) => Number(box.value));

function syncSelection() {
  const boxes = checkboxes();
  const selected = selectedIds();
  const selectPage = document.getElementById("selectPage");
  const batchBar = document.getElementById("batchBar");
  if (!selectPage || !batchBar) return;
  selectPage.checked = boxes.length > 0 && selected.length === boxes.length;
  selectPage.indeterminate = selected.length > 0 && selected.length < boxes.length;
  document.getElementById("selectedCount").textContent = selected.length;
  batchBar.hidden = selected.length === 0;
}

async function batch(action, ids, controls) {
  controls.forEach((control) => { control.disabled = true; });
  try {
    const response = await fetch("/api/events/batch", {
      method: "POST",
      cache: "no-store",
      headers: {"Content-Type": "application/json", "Accept": "application/json", "X-CSRF-Token": csrf},
      body: JSON.stringify({action, ids}),
    });
    if (response.status === 401) {
      location.assign("/login");
      return;
    }
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* nginx error page */ }
    if (!response.ok) throw new Error(payload.error || "操作失败，请稍后重试。");
    const changed = payload.updated || payload.deleted || [];
    changed.concat(payload.missing || []).forEach((id) => {
      const card = document.querySelector(`.event-card[data-event-id="${id}"]`);
      if (!card) return;
      if (action === "delete") {
        card.remove();
      } else {
        card.classList.remove("unseen");
        const tag = card.querySelector(".event-tag");
        if (tag && card.dataset.kind === "motion") tag.textContent = "移动";
        card.querySelector('form[data-action="viewed"]')?.remove();
        if (new URLSearchParams(location.search).get("filter") === "unseen") card.remove();
      }
    });
    syncSelection();
    toast(action === "delete" ? `已删除 ${changed.length} 个事件及其图片。` : `已确认 ${changed.length} 个事件。`);
    if (!document.querySelector(".event-card")) setTimeout(() => location.reload(), 500);
  } catch (error) {
    toast(error.message || "连接暂时不可用，请稍后重试。");
  } finally {
    controls.forEach((control) => { control.disabled = false; });
  }
}

document.querySelectorAll(".event-checkbox").forEach((box) => box.addEventListener("change", syncSelection));
document.getElementById("selectPage")?.addEventListener("change", (event) => {
  checkboxes().forEach((box) => { box.checked = event.target.checked; });
  syncSelection();
});

document.querySelectorAll("form.event-action").forEach((form) => form.addEventListener("submit", (event) => {
  event.preventDefault();
  const card = form.closest(".event-card");
  const action = form.dataset.action;
  if (action === "delete" && !window.confirm("删除这个事件及其全部照片？此操作不能撤销。")) return;
  batch(action, [Number(card.dataset.eventId)], Array.from(form.querySelectorAll("button")));
}));

document.getElementById("batchViewed")?.addEventListener("click", (event) => {
  const ids = selectedIds();
  if (ids.length) batch("viewed", ids, [event.currentTarget, document.getElementById("batchDelete")]);
});
document.getElementById("batchDelete")?.addEventListener("click", (event) => {
  const ids = selectedIds();
  if (!ids.length || !window.confirm(`删除所选 ${ids.length} 个事件及其全部照片？此操作不能撤销。`)) return;
  batch("delete", ids, [event.currentTarget, document.getElementById("batchViewed")]);
});

document.getElementById("clearAllEvents")?.addEventListener("click", async (event) => {
  if (!window.confirm("确定清空所有活动事件吗？这会永久删除全部事件记录及图片，无法撤销。")) return;
  const button = event.currentTarget;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "正在清空…";
  try {
    const response = await fetch("/api/events/clear", {
      method: "POST",
      cache: "no-store",
      headers: {"Content-Type": "application/json", "Accept": "application/json", "X-CSRF-Token": csrf},
      body: JSON.stringify({confirm: true}),
    });
    if (response.status === 401) {
      location.assign("/login");
      return;
    }
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* nginx error page */ }
    if (!response.ok) throw new Error(payload.error || "清空失败，请稍后重试。");
    toast(`已清空 ${payload.deleted_count || 0} 个事件及其图片。`);
    setTimeout(() => location.assign("/events"), 650);
  } catch (error) {
    toast(error.message || "连接暂时不可用，请稍后重试。");
    button.disabled = false;
    button.textContent = original;
  }
});
