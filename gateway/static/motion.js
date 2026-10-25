"use strict";
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const editor = document.getElementById("roiEditor"), image = document.getElementById("roiImage");
const box = document.getElementById("roiBox"), form = document.getElementById("motionForm");
const fields = ["roiX", "roiY", "roiW", "roiH"].map((id) => document.getElementById(id));
let start = null, toastTimer;

function values() { return fields.map((field) => Number(field.value)); }
function setValues(x, y, w, h) { [x, y, w, h].forEach((value, index) => { fields[index].value = value.toFixed(4); }); render(); }
function render() {
  const [x, y, w, h] = values();
  Object.assign(box.style, {left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%`});
}
function point(event) {
  const rect = image.getBoundingClientRect();
  return {x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)), y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))};
}
function notify(message) {
  const node = document.getElementById("toast"); node.textContent = message; node.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { node.hidden = true; }, 4000);
}
editor.addEventListener("pointerdown", (event) => { start = point(event); editor.setPointerCapture(event.pointerId); event.preventDefault(); });
editor.addEventListener("pointermove", (event) => {
  if (!start) return; const current = point(event);
  const x = Math.min(.95, Math.min(start.x, current.x)), y = Math.min(.95, Math.min(start.y, current.y));
  setValues(x, y, Math.min(1 - x, Math.max(0.05, Math.abs(current.x - start.x))), Math.min(1 - y, Math.max(0.05, Math.abs(current.y - start.y))));
});
editor.addEventListener("pointerup", () => { start = null; });
document.getElementById("fullFrame").addEventListener("click", () => setValues(0, 0, 1, 1));
document.getElementById("pixelThreshold").addEventListener("input", (event) => { document.getElementById("pixelValue").value = event.target.value; });
document.getElementById("areaRatio").addEventListener("input", (event) => { document.getElementById("areaValue").value = `${Number(event.target.value).toFixed(1)}%`; });
form.addEventListener("submit", async (event) => {
  event.preventDefault(); const button = form.querySelector("button[type=submit]"); button.disabled = true;
  const [roi_x, roi_y, roi_w, roi_h] = values();
  try {
    const response = await fetch("/api/motion-settings", {method: "POST", cache: "no-store", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}, body: JSON.stringify({roi_x, roi_y, roi_w, roi_h, pixel_threshold: Number(document.getElementById("pixelThreshold").value), area_ratio: Number(document.getElementById("areaRatio").value) / 100})});
    const result = await response.json(); if (!response.ok) throw new Error(result.error || "保存失败。"); notify("检测区域已保存，背景模型正在重新学习。");
  } catch (error) { notify(error.message); } finally { button.disabled = false; }
});
image.addEventListener("load", render); render();
