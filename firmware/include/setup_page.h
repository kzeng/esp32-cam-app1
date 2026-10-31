#pragma once

// Self-contained UI; the HTTP server replaces the two placeholders.
constexpr const char SETUP_PAGE[] = R"HTML(<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>为设备连接 Wi-Fi</title>
<style>
:root{--bg:#f6f4ed;--paper:#fffefa;--ink:#253d32;--muted:#67766a;--green:#23734c;--line:#dedfd4;--soft:#edf4e9}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}button,input{font:inherit;min-height:48px}button{cursor:pointer;touch-action:manipulation;border:1px solid var(--line);border-radius:12px;background:var(--paper);color:var(--ink);padding:10px 15px}button:disabled{cursor:wait;opacity:.6}button:focus-visible,input:focus-visible{outline:3px solid #80b98b;outline-offset:3px}button:hover:not(:disabled){background:var(--soft)}[hidden]{display:none!important}.shell{max-width:560px;margin:auto;padding:40px 20px calc(28px + env(safe-area-inset-bottom))}.brand{display:flex;align-items:center;gap:12px;margin-bottom:28px;font-weight:700}.mark{display:grid;place-items:center;width:46px;height:46px;border-radius:16px;background:var(--green);color:white;font-size:28px}.brand small{display:block;font-size:12px;font-weight:400;letter-spacing:.12em;color:var(--muted)}.card{background:var(--paper);border:1px solid var(--line);border-radius:24px;padding:28px;box-shadow:0 14px 44px #334e3210}.step{display:inline-block;font-size:12px;font-weight:700;color:var(--green);background:var(--soft);padding:5px 11px;border-radius:20px}h1{font-size:28px;line-height:1.3;margin:16px 0 10px}.intro{margin:0 0 26px;color:var(--muted);font-size:14px}.field{margin:22px 0}.label-row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}label{font-weight:650;font-size:14px}.refresh{font-size:14px;color:var(--green);padding:8px 12px;min-height:44px}.input-wrap{position:relative;display:flex}input:not([type=hidden]){width:100%;min-width:0;border:1px solid #cbd2c6;border-radius:12px;background:white;padding:12px 14px;color:var(--ink);font-size:16px}.input-wrap input{padding-right:72px}.inside{position:absolute;right:3px;top:3px;bottom:3px;min-height:44px;border:0;border-radius:9px;background:transparent;font-size:14px;color:var(--green)}.hint,.status{font-size:12px;color:var(--muted);margin:8px 0 0;overflow-wrap:anywhere}.status{min-height:20px}.status[data-kind=error]{color:#a63c2f}.dropdown{position:relative}.list{position:absolute;top:calc(100% + 6px);left:0;right:0;z-index:5;max-height:260px;overflow-y:auto;overscroll-behavior:contain;background:white;border:1px solid var(--line);border-radius:12px;box-shadow:0 12px 28px #253d3220;padding:5px;margin:0;list-style:none}.option{padding:10px;border-radius:8px;min-height:56px;cursor:pointer}.option[aria-selected=true]{background:var(--soft);outline:1px solid #9cbe9a;outline-offset:-1px}.network-name{display:block;font-size:15px;font-weight:600;overflow-wrap:anywhere;white-space:pre-wrap}.network-meta{display:block;font-size:12px;color:var(--muted)}.empty{padding:14px;font-size:13px;color:var(--muted)}.notice{border-radius:12px;background:#f6f3e8;padding:12px 14px;font-size:12px;color:#73694d;margin:24px 0 18px}.primary{width:100%;background:var(--green);border-color:var(--green);color:white;font-weight:700;min-height:52px}.primary:hover:not(:disabled){background:#195e3b}.cancel{text-align:center;margin-top:12px}.cancel button{background:transparent;border-color:transparent;color:var(--muted);font-size:14px}.footer{text-align:center;color:var(--muted);font-size:12px;margin:20px 0}noscript p{font-size:14px;color:#a63c2f}@media(max-width:380px){.shell{padding:22px 12px}.card{padding:22px 18px}h1{font-size:25px}}
</style>
</head>
<body>
<main class="shell">
<header class="brand"><span class="mark" aria-hidden="true">⌁</span><div>设备配网<small>让连接，简单一点</small></div></header>
<section class="card" aria-labelledby="title">
<span class="step">开始连接 · WI-FI 设置</span>
<h1 id="title">给设备一个家的连接</h1>
<p class="intro">选择家中的 Wi-Fi，填写密码。完成后，设备将尝试连接到你的网络。</p>
<form id="configure" method="POST" action="/configure">
<input type='hidden' name='token' value='{{TOKEN}}'>
<div class="field">
<div class="label-row"><label for="ssid">Wi-Fi 名称</label><button class="refresh" id="refresh" type="button">↻ 刷新网络</button></div>
<div class="dropdown" id="network-picker">
<div class="input-wrap"><input id="ssid" name="ssid" type="text" required autocomplete="off" autocapitalize="none" spellcheck="false" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="networks" aria-describedby="ssid-hint scan-status" placeholder="选择或手动输入 Wi-Fi 名称"><button class="inside" id="toggle-networks" type="button" aria-label="展开 Wi-Fi 列表" aria-controls="networks" aria-expanded="false">⌄</button></div>
<ul class="list" id="networks" role="listbox" aria-label="可用 Wi-Fi 网络" hidden></ul>
</div>
<p class="hint" id="ssid-hint">支持手动输入隐藏网络名称。请优先选择 2.4 GHz Wi-Fi。</p>
<p class="status" id="scan-status" role="status" aria-live="polite" aria-atomic="true">正在准备扫描附近网络…</p>
</div>
<div class="field"><div class="label-row"><label for="password">Wi-Fi 密码</label></div><div class="input-wrap"><input id="password" name="password" type="password" autocomplete="new-password" aria-describedby="password-hint" placeholder="输入网络密码" autocapitalize="none" spellcheck="false"><button class="inside" id="show-password" type="button" aria-pressed="false" aria-label="显示密码">显示</button></div><p class="hint" id="password-hint">开放网络无需填写密码。</p></div>
<div class="field"><div class="label-row"><label for="hostname">设备主机名</label></div><input id="hostname" name="hostname" value="{{HOSTNAME}}" type="text" required minlength="1" maxlength="32" pattern="[a-z0-9]([a-z0-9\-]{0,30}[a-z0-9])?" autocomplete="off" autocapitalize="none" spellcheck="false" aria-describedby="hostname-hint"><p class="hint" id="hostname-hint">1–32 位小写字母、数字或连字符，首尾不能是连字符。</p></div>
<div class="notice">连接时配网热点可能会断开，请稍候，再让手机连接回目标 Wi-Fi。</div>
<button class="primary" id="submit" type="submit">保存并连接 Wi-Fi</button>
<p class="status" id="form-status" role="status" aria-live="polite"></p>
</form>
<form class="cancel" method="POST" action="/cancel"><input type='hidden' name='token' value='{{TOKEN}}'><button type="submit">取消配网</button></form>
<noscript><p>浏览器未启用 JavaScript，无法扫描网络；仍可手动填写并保存设置。</p></noscript>
</section>
<p class="footer">● 本地设备配网 · 无需访问互联网</p>
</main>
<script>
(function () {
'use strict';
const $ = id => document.getElementById(id);
const form = $('configure'), ssid = $('ssid'), list = $('networks');
const toggle = $('toggle-networks'), refresh = $('refresh'), status = $('scan-status');
const hostname = $('hostname');
let networks = [], visible = [], active = -1, scanning = false, submitting = false;
let controller = null, scanVersion = 0;
let scanError = '', scanned = false;
function message(text, error) {
  status.textContent = text;
  status.dataset.kind = error ? 'error' : 'info';
}
function expanded(open) {
  list.hidden = !open;
  ssid.setAttribute('aria-expanded', String(open));
  toggle.setAttribute('aria-expanded', String(open));
  toggle.setAttribute('aria-label', open ? '收起 Wi-Fi 列表' : '展开 Wi-Fi 列表');
  if (!open) setActive(-1);
}
function setActive(index) {
  active = index;
  Array.from(list.children).forEach((node, i) => {
    if (node.getAttribute('role') === 'option') node.setAttribute('aria-selected', String(i === index));
  });
  if (index >= 0 && list.children[index]) {
    ssid.setAttribute('aria-activedescendant', list.children[index].id);
    list.children[index].scrollIntoView({block: 'nearest'});
  } else ssid.removeAttribute('aria-activedescendant');
}
function choose(index) {
  if (!visible[index]) return;
  ssid.value = visible[index].ssid;
  ssid.setCustomValidity('');
  expanded(false);
  ssid.focus();
}
function render() {
  list.replaceChildren(); active = -1;
  ssid.removeAttribute('aria-activedescendant');
  const query = ssid.value.toLocaleLowerCase();
  visible = networks.filter(n => n.ssid.toLocaleLowerCase().includes(query));
  visible.forEach((network, index) => {
    const row = document.createElement('li');
    row.className = 'option'; row.id = 'network-' + index;
    row.setAttribute('role', 'option'); row.setAttribute('aria-selected', 'false');
    const name = document.createElement('span'); name.className = 'network-name';
    name.textContent = network.ssid;
    const meta = document.createElement('span'); meta.className = 'network-meta';
    const level = network.rssi >= -55 ? '▂▄▆█ 强' : network.rssi >= -67 ? '▂▄▆ 中' : network.rssi >= -80 ? '▂▄ 弱' : '▂ 很弱';
    meta.textContent = (network.secure ? '安全 · 需要密码' : '开放 · 无密码') + '  ·  ' + level + ' (' + network.rssi + ' dBm)';
    row.append(name, meta);
    row.addEventListener('click', () => choose(index));
    list.appendChild(row);
  });
  if (!visible.length) {
    const empty = document.createElement('li'); empty.className = 'empty';
    empty.setAttribute('role', 'presentation');
    empty.textContent = scanning ? '正在扫描，请稍候…' : scanError ? scanError : networks.length ? '没有匹配的网络，可直接输入隐藏网络名称。' : scanned ? '未发现 2.4 GHz 网络，可刷新或手动输入。' : '尚未扫描，请点击刷新网络。';
    list.appendChild(empty);
  }
}
ssid.addEventListener('input', () => { ssid.setCustomValidity(''); render(); expanded(true); });
ssid.addEventListener('click', () => { render(); expanded(true); });
toggle.addEventListener('click', () => {
  const open = list.hidden;
  ssid.focus(); render(); expanded(open);
});
ssid.addEventListener('keydown', event => {
  if (event.isComposing) return;
  if (event.key === 'Escape') { expanded(false); event.preventDefault(); }
  else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    if (list.hidden) { render(); expanded(true); }
    if (visible.length) setActive(active < 0 ? (event.key === 'ArrowDown' ? 0 : visible.length - 1) : (active + (event.key === 'ArrowDown' ? 1 : -1) + visible.length) % visible.length);
  } else if (event.key === 'Enter' && !list.hidden) {
    event.preventDefault();
    if (active >= 0) choose(active); else expanded(false);
  } else if (event.key === 'Tab') expanded(false);
});
document.addEventListener('pointerdown', event => {
  if (!$('network-picker').contains(event.target)) expanded(false);
});
$('network-picker').addEventListener('focusout', event => {
  if (!$('network-picker').contains(event.relatedTarget)) expanded(false);
});
$('show-password').addEventListener('click', () => {
  const show = $('password').type === 'password';
  $('password').type = show ? 'text' : 'password';
  $('show-password').textContent = show ? '隐藏' : '显示';
  $('show-password').setAttribute('aria-pressed', String(show));
  $('show-password').setAttribute('aria-label', show ? '隐藏密码' : '显示密码');
});
// Keep keyboard focus on the combobox when selecting with a mouse or touch.
list.addEventListener('mousedown', event => event.preventDefault());
async function request(options, deadline) {
  const remaining = deadline - Date.now();
  if (remaining <= 0) throw new Error('扫描已超过 35 秒，请刷新重试。');
  controller = new AbortController();
  const current = controller;
  const timer = setTimeout(() => current.abort(), Math.min(6000, remaining));
  try {
    const response = await fetch('/scan', Object.assign({cache: 'no-store', credentials: 'same-origin'}, options, {signal: current.signal}));
    if (response.status === 409) throw new Error('设备正在配网，请稍候再扫描。');
    if (response.status === 429) throw new Error('扫描过于频繁，请稍候再点击刷新。');
    if (!response.ok) throw new Error('扫描请求失败（' + response.status + '），请刷新重试。');
    const data = await response.json();
    if (!data || typeof data !== 'object') throw new Error('设备返回的数据格式异常，请重试。');
    if (typeof data.error === 'string' && data.error) throw new Error(data.error);
    return {pending: response.status === 202 || data.scanning === true, data: data};
  } finally {
    clearTimeout(timer);
    if (controller === current) controller = null;
  }
}
async function scan() {
  if (scanning || submitting) return;
  if (typeof fetch !== 'function' || typeof AbortController !== 'function') {
    message('当前浏览器不支持自动扫描，请手动输入 Wi-Fi 名称。', true); return;
  }
  const version = ++scanVersion;
  const deadline = Date.now() + 35000;
  scanError = '';
  scanning = true; refresh.disabled = true;
  refresh.textContent = '扫描中…';
  message('正在扫描附近的 Wi-Fi，请稍候…'); render();
  try {
    let result = await request({method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: new URLSearchParams({token: form.elements.token.value}).toString()}, deadline);
    while (result.pending) {
      if (version !== scanVersion) return;
      const remaining = deadline - Date.now();
      if (remaining <= 1000) throw new Error('扫描已超过 35 秒，请刷新重试。');
      await new Promise(resolve => setTimeout(resolve, 1000));
      if (version !== scanVersion) return;
      result = await request({method: 'GET'}, deadline);
    }
    if (version !== scanVersion) return;
    if (result.data.error) throw new Error(result.data.error);
    if (!Array.isArray(result.data.networks)) throw new Error('网络列表格式异常，请刷新重试。');
    networks = result.data.networks.filter(n => n && typeof n.ssid === 'string' && n.ssid.length > 0 && Number.isFinite(n.rssi) && typeof n.secure === 'boolean').sort((a, b) => b.rssi - a.rssi);
    scanned = true;
    message(networks.length ? '找到 ' + networks.length + ' 个网络，点击名称输入框选择。' : '未发现可用网络。请靠近路由器刷新，或手动输入隐藏网络名称。');
  } catch (error) {
    if (version !== scanVersion) return;
    scanError = error.name === 'AbortError' ? '扫描请求超时，请刷新重试；也可手动输入网络。' : (error instanceof TypeError ? '无法连接设备，请确认手机仍连接配网热点后重试。' : error.message);
    message(scanError, true);
  } finally {
    if (version === scanVersion) {
      scanning = false; refresh.disabled = false;
      refresh.textContent = '↻ 刷新网络'; render();
    }
  }
}
refresh.addEventListener('click', scan);
function validateHostname() {
  hostname.setCustomValidity(/^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/.test(hostname.value) ? '' : '请输入 1–32 位小写字母、数字或连字符，且首尾不能是连字符。');
}
hostname.addEventListener('input', validateHostname);
// Validate UTF-8 byte length without trimming: spaces may be part of an SSID.
function validateSsid() {
  const bytes = new Blob([ssid.value]).size;
  ssid.setCustomValidity(bytes > 32 ? 'Wi-Fi 名称不能超过 32 字节（中文通常占 3 字节）。' : '');
}
ssid.addEventListener('input', validateSsid);
form.addEventListener('submit', event => {
  validateHostname(); validateSsid();
  if (submitting || !form.reportValidity()) { event.preventDefault(); return; }
  submitting = true; ++scanVersion;
  if (controller) controller.abort();
  expanded(false); refresh.disabled = true; $('submit').disabled = true;
  $('submit').textContent = '正在保存并连接…';
  $('form-status').textContent = '正在提交设置，热点可能断开，请稍候。';
});
window.addEventListener('pagehide', () => { ++scanVersion; if (controller) controller.abort(); });
window.addEventListener('pageshow', event => {
  if (event.persisted) {
    submitting = false; scanning = false; refresh.disabled = false;
    refresh.textContent = '↻ 刷新网络'; $('submit').disabled = false;
    $('submit').textContent = '保存并连接 Wi-Fi'; $('form-status').textContent = '';
    scan();
  }
});
scan();
})();
</script>
</body>
</html>)HTML";
