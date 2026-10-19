"use strict";
const $ = (id) => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let watching = false, resumeWhenVisible = false, streamStarted = 0;
let previousSequence = -1, stalledPolls = 0, photoUrl = null, toastTimer;
let effectiveResolution = "";

$("today").textContent = new Intl.DateTimeFormat("zh-CN", {month: "long", day: "numeric", weekday: "short"}).format(new Date());

function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, 5000);
}

async function api(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  let response;
  try {
    response = await fetch(url, {cache: "no-store", ...options, signal: controller.signal});
  } catch (error) {
    if (error.name === "AbortError") throw new Error("连接超时，请检查网络后重试。");
    throw new Error("无法连接家中电脑，请检查远程连接。");
  } finally { clearTimeout(timeout); }
  if (response.status === 401) {
    stop();
    location.assign("/login");
    throw new Error("请重新登录。");
  }
  if (!response.ok) {
    let message = "请求失败，请稍后重试。";
    try { message = (await response.json()).error || message; } catch (_) { /* HTTP error without JSON */ }
    throw new Error(message);
  }
  return response;
}

function overlay(title, text) {
  $("placeholderTitle").textContent = title;
  $("placeholderText").textContent = text;
  $("placeholder").hidden = false;
}

function connectStream() {
  if (!watching) return;
  streamStarted = Date.now();
  stalledPolls = 0;
  $("stream").src = `/api/stream?t=${streamStarted}`;
  $("stream").hidden = false;
}

function start() {
  watching = true;
  $("toggle").textContent = "暂停观看";
  $("state").textContent = "正在连接";
  overlay("正在打开小窝", "等待摄像头画面，连接恢复后会自动继续。");
  connectStream();
}

function stop() {
  watching = false;
  $("stream").removeAttribute("src");
  $("stream").hidden = true;
  $("toggle").textContent = "开始观看";
  $("state").textContent = "已暂停";
  $("statusDot").className = "dot";
  overlay("画面已暂停", "点击开始观看，重新连接家里的小伙伴。");
  $("connectionNote").textContent = "此页面已暂停接收画面。";
}

$("toggle").addEventListener("click", () => {
  resumeWhenVisible = false;
  if (watching) stop(); else start();
});

async function poll() {
  if (document.hidden) return;
  try {
    const data = await (await api("/api/status")).json();
    if (data.resolution && !$("quality").disabled) {
      effectiveResolution = data.resolution;
      $("quality").value = effectiveResolution;
    }
    if (!watching) return;
    if (data.sequence === previousSequence) stalledPolls++; else stalledPolls = 0;
    previousSequence = data.sequence;
    const live = data.state === "live";
    $("state").textContent = live ? "画面更新中" : data.state === "offline" ? "连接中断" : "正在连接";
    $("statusDot").className = `dot ${live ? "live" : data.state === "offline" ? "offline" : ""}`;
    if (live) {
      $("placeholder").hidden = true;
      $("connectionNote").textContent = `最近收到画面：${data.frame_age_s} 秒前`;
    } else {
      overlay("正在连接小窝", data.error || "等待摄像头画面，恢复后会自动继续。");
      $("connectionNote").textContent = data.error || "正在等待画面。";
    }
    if ((data.state === "idle" || !live || stalledPolls >= 3) && Date.now() - streamStarted > 12000) {
      connectStream();
    }
  } catch (error) {
    if (!watching) return;
    $("state").textContent = "电脑连接中断";
    $("statusDot").className = "dot offline";
    overlay("暂时连接不上", "请确认手机的远程连接已开启，家中电脑仍在运行。");
    $("connectionNote").textContent = error.message;
  }
}

$("stream").addEventListener("error", () => {
  if (watching) overlay("正在重新连接", "连接恢复后会自动继续播放。");
});

$("stream").addEventListener("load", () => {
  if (!watching) return;
  const image = $("stream");
  if (image.naturalWidth) $("resolutionLabel").textContent = `${image.naturalWidth} × ${image.naturalHeight}`;
});

$("quality").addEventListener("change", async () => {
  const select = $("quality");
  const requested = select.value;
  select.disabled = true;
  try {
    await api("/api/quality", {
      method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf},
      body: JSON.stringify({resolution: requested}),
    });
    effectiveResolution = requested;
    $("resolutionLabel").textContent = {low: "320 × 240", standard: "640 × 480", high: "800 × 600"}[requested];
    toast("画质已调整。此设置对所有观看者生效。");
  } catch (error) {
    select.value = effectiveResolution;
    toast(error.message);
  } finally { select.disabled = false; }
});

$("snapshot").addEventListener("click", async () => {
  const button = $("snapshot");
  button.disabled = true;
  button.textContent = "正在拍照…";
  try {
    const response = await api("/api/snapshot");
    const blob = await response.blob();
    if (photoUrl) URL.revokeObjectURL(photoUrl);
    photoUrl = URL.createObjectURL(blob);
    $("photoPreview").src = photoUrl;
    const download = $("photoDownload");
    download.href = photoUrl;
    download.download = `pet-${new Date().toISOString().replace(/[:.]/g, "-")}.jpg`;
    $("photoTray").hidden = false;
    // Explicit download link also works on mobile browsers that block async automatic downloads.
    toast("拍照完成，点击“下载照片”保存。");
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = "拍照保存"; }
});

$("fullscreen").addEventListener("click", async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else if ($("viewport").requestFullscreen) await $("viewport").requestFullscreen();
    else toast("当前浏览器不支持全屏，可以横屏查看。");
  } catch (_) { toast("当前浏览器无法进入全屏，可以横屏查看。"); }
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) { resumeWhenVisible = watching; if (watching) stop(); }
  else if (resumeWhenVisible) { resumeWhenVisible = false; start(); }
});
window.addEventListener("pagehide", () => { stop(); if (photoUrl) URL.revokeObjectURL(photoUrl); });
// Recursive timer avoids stacking requests when a network connection stalls.
async function tick() {
  try { await poll(); } finally { setTimeout(tick, 3000); }
}
tick();
