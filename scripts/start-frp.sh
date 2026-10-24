#!/usr/bin/env bash
# Start Pet Watch locally and expose it through the frp tunnel.
# Public entry: https://hamster.mitoto.cn (override with FRP_PUBLIC_URL).
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY="$ROOT/gateway"
GUNICORN="$ROOT/.venv/bin/gunicorn"
FRPC_BIN="${FRPC_BIN:-frpc}"
FRPC_CONFIG="${FRPC_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/frp/frpc.toml}"
FRPC_SERVICE="${FRPC_SERVICE:-frpc}"
PUBLIC_URL="${FRP_PUBLIC_URL:-https://hamster.mitoto.cn}"
LOCAL_URL='http://127.0.0.1:8080'
LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/pet-watch-frp-${UID}.lock"
gateway_pid=''
frpc_pid=''
log_dir=''

usage() {
  cat <<'EOF'
用法：scripts/start-frp.sh [--status | --help]

默认启动：先启动网页网关（如尚未运行），再确保 frp 隧道在线。
手机访问脚本打印的 HTTPS 地址。按 Ctrl+C 关闭由本脚本启动的进程。

隧道优先复用 systemd 用户服务 frpc；没有在跑时才由本脚本后台启动 frpc
（配置默认 ~/.config/frp/frpc.toml）。

--status：查看网关、frp 隧道和公网地址状态，不启动任何服务。

可覆盖的环境变量：FRP_PUBLIC_URL、FRPC_CONFIG、FRPC_BIN、FRPC_SERVICE。
EOF
}

health() {
  local response
  response="$(curl --noproxy '*' -fsS --max-time 3 "$LOCAL_URL/healthz" 2>/dev/null)" || return 1
  [[ "$response" == '{"ok":true}' ]]
}

public_health() {
  local response
  response="$(curl --noproxy '*' -fsS --max-time 8 "$PUBLIC_URL/healthz" 2>/dev/null)" || return 1
  [[ "$response" == '{"ok":true}' ]]
}

frpc_systemd_active() {
  systemctl --user is-active --quiet "$FRPC_SERVICE" 2>/dev/null
}

frpc_process_running() {
  pgrep -x frpc >/dev/null 2>&1
}

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "$frpc_pid" ]]; then
    kill -TERM "$frpc_pid" 2>/dev/null || true
    wait "$frpc_pid" 2>/dev/null || true
  fi
  if [[ -n "$gateway_pid" ]]; then
    kill -TERM "$gateway_pid" 2>/dev/null || true
    wait "$gateway_pid" 2>/dev/null || true
  fi
  if [[ -n "$log_dir" ]]; then
    rm -f -- "$log_dir/gateway.log" "$log_dir/frpc.log"
    rmdir -- "$log_dir" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "${1:-}" == '--help' ]]; then usage; exit 0; fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != '--status' ) ]]; then usage >&2; exit 2; fi
for program in curl pgrep; do
  command -v "$program" >/dev/null || { echo "缺少依赖：$program" >&2; exit 1; }
done

if [[ "${1:-}" == '--status' ]]; then
  if health; then echo "网页网关：$LOCAL_URL"; else echo '网页网关：未就绪'; fi
  if frpc_systemd_active; then
    echo "frp 隧道：systemd 用户服务 $FRPC_SERVICE 运行中"
  elif frpc_process_running; then
    echo 'frp 隧道：frpc 进程运行中'
  else
    echo 'frp 隧道：未运行'
  fi
  if public_health; then echo "手机 HTTPS 地址：$PUBLIC_URL"; else echo "公网入口：$PUBLIC_URL 暂不可用"; fi
  exit 0
fi

command -v flock >/dev/null || { echo '缺少依赖：flock（util-linux）' >&2; exit 1; }
[[ -x "$GUNICORN" ]] || { echo "找不到 $GUNICORN，请先安装 gateway/requirements.txt。" >&2; exit 1; }
[[ -f "$GATEWAY/.env" ]] || { echo "缺少 $GATEWAY/.env。" >&2; exit 1; }
exec 9>"$LOCK_FILE"
flock -n 9 || { echo '本脚本已在另一个终端运行。' >&2; exit 1; }

log_dir="$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/pet-watch-frp.XXXXXXXX")"
chmod 700 "$log_dir"

if health; then
  echo '已有网页网关运行中；不会修改或停止它。'
else
  echo '正在启动网页网关…'
  (cd "$GATEWAY" && exec "$GUNICORN" --workers 1 --threads 16 --bind 0.0.0.0:8080 app:app) >"$log_dir/gateway.log" 2>&1 &
  gateway_pid=$!
  ready=0
  for ((i=0; i<30; i++)); do
    if health; then ready=1; break; fi
    if ! kill -0 "$gateway_pid" 2>/dev/null; then break; fi
    sleep 1
  done
  if (( ! ready )); then
    echo '网页网关启动失败，日志：' >&2
    tail -n 15 "$log_dir/gateway.log" >&2
    exit 1
  fi
fi

if frpc_systemd_active; then
  echo "复用已在运行的 systemd 用户服务：$FRPC_SERVICE"
elif frpc_process_running; then
  echo '复用已在运行的 frpc 进程。'
else
  resolved_frpc="$(command -v "$FRPC_BIN" 2>/dev/null || true)"
  [[ -n "$resolved_frpc" && -x "$resolved_frpc" ]] || { echo "找不到 frpc（$FRPC_BIN）；请安装 frp 客户端或设置 FRPC_BIN。" >&2; exit 1; }
  [[ -f "$FRPC_CONFIG" ]] || { echo "缺少 frp 配置：$FRPC_CONFIG" >&2; exit 1; }
  echo '正在启动 frp 客户端…'
  "$resolved_frpc" -c "$FRPC_CONFIG" >"$log_dir/frpc.log" 2>&1 &
  frpc_pid=$!
fi

ready=0
for ((i=0; i<60; i++)); do
  if public_health; then ready=1; break; fi
  if [[ -n "$frpc_pid" ]] && ! kill -0 "$frpc_pid" 2>/dev/null; then break; fi
  sleep 1
done
if (( ! ready )); then
  echo "公网入口 $PUBLIC_URL 未就绪，日志：" >&2
  if [[ -n "$log_dir" && -f "$log_dir/frpc.log" ]]; then tail -n 15 "$log_dir/frpc.log" >&2; fi
  echo '排查：systemctl --user status frpc；查看 ~/.config/frp/frpc.log；确认 kzeng 上 frps 与 nginx 正常。' >&2
  exit 1
fi

echo "手机 HTTPS 地址：$PUBLIC_URL"
echo '监控网页仍需要登录密码；不要把这个地址当作密码。'
echo '按 Ctrl+C 停止本脚本启动的服务。'

while :; do
  if [[ -n "$frpc_pid" ]] && ! kill -0 "$frpc_pid" 2>/dev/null; then
    echo 'frp 客户端已退出，日志：' >&2
    tail -n 15 "$log_dir/frpc.log" >&2
    exit 1
  fi
  if [[ -z "$frpc_pid" ]] && ! frpc_systemd_active && ! frpc_process_running; then
    echo 'frp 隧道已断开：systemd 服务与 frpc 进程均不在运行。' >&2
    exit 1
  fi
  if [[ -n "$gateway_pid" ]] && ! kill -0 "$gateway_pid" 2>/dev/null; then
    echo '网页网关意外退出，日志：' >&2
    tail -n 15 "$log_dir/gateway.log" >&2
    exit 1
  fi
  sleep 2
done
