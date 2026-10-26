# frp：一键启动与手机访问

外网入口固定为 **https://hamster.mitoto.cn**：Let's Encrypt 证书终止在 kzeng 云服务器，
再经 frp 隧道转发到本机网关。不再使用 ngrok。

## 组成

- **云服务器 kzeng（47.97.193.62）**：frps 监听 `7000`（token 认证，只放行 8080 映射）；
  nginx 监听 443，把 `hamster.mitoto.cn` 反代到 `127.0.0.1:8080`。
- **本机**：frpc 以 systemd 用户服务 `frpc` 常驻，配置 `~/.config/frp/frpc.toml`，
  把 `127.0.0.1:8080` 映射到服务器的 8080。
- **网关**：gunicorn 监听 `0.0.0.0:8080`。

链路：手机 → HTTPS(443, kzeng/nginx) → 127.0.0.1:8080(frps) → frp 隧道 → 本机 gunicorn。

## 一键启动

在仓库根目录执行：

```bash
./scripts/start-frp.sh
```

脚本会确认 `gateway/.env`、Python 虚拟环境；网关未运行时以单 worker、16 线程启动并监听
`0.0.0.0:8080`（供本机和家庭局域网访问）。隧道优先复用已在运行的 systemd 用户服务 `frpc`；
只有服务未运行时才由脚本后台启动 `frpc -c ~/.config/frp/frpc.toml`。

随后脚本请求 `https://hamster.mitoto.cn/healthz` 确认真实可用，再打印手机地址。

脚本运行期间保持终端打开。`Ctrl+C` 只停止由本脚本启动的进程，不会停止 systemd 管理的
`frpc`，也不会停止原先已运行的网关。

仅查询状态：

```bash
./scripts/start-frp.sh --status
```

可覆盖的环境变量：`FRP_PUBLIC_URL`（默认 `https://hamster.mitoto.cn`）、`FRPC_CONFIG`、
`FRPC_BIN`、`FRPC_SERVICE`。

## 手机访问

关闭 Wi-Fi，用移动数据打开 `https://hamster.mitoto.cn`，登录监控网页即可。
手机无需安装任何客户端，路由器无需端口转发。地址固定，不像 ngrok 每次启动都变。

## 服务器侧（只在 kzeng 上）

- frps：`systemctl status frps`，配置 `/etc/frp/frps.toml`，日志 `/var/log/frps.log`
- nginx：虚拟主机 `/etc/nginx/sites-available/hamster.mitoto.cn`
- 证书：`/etc/letsencrypt/live/hamster.mitoto.cn/`，由 `certbot.timer` 自动续期
- 续期依赖 `certbot.service.d/override.conf` 里的 `PYTHONPATH` 修正（系统 urllib3 被
  `/usr/local` 下 pip 版本遮蔽的问题）

## 安全与限制

- 公网入口，网页访问密码应至少 12 位，不要重用 Wi-Fi 密码，也不要用发在聊天记录里的密码。
- 手机到服务器是标准 HTTPS；服务器到本机走 frp token 认证的隧道。
- frps 的 `proxyBindAddr` 固定为 `127.0.0.1`，服务器 `8080` 仅供本机 nginx 使用，不对公网提供明文入口。
- frpc 与 frps 均关闭 TCP 多路复用；frpc 预建 10 条工作连接，frps 允许每个代理最多 20 条连接池。两端改动后分别重启服务并检查日志。
- frpc 用 `transport.connectServerLocalIP` 绑定当前家庭网卡地址，防止控制连接被 Mihomo TUN 送到代理出口；本机 LAN 地址变化时要同步更新该值。
- nginx 只把 Pet Watch 已知路由转入隧道，对未知扫描路径直接返回 404；页面与 API 设置每 IP 请求速率和并发限制，超额返回 429。带版本号的静态资源和事件图片不参与这两个计数，避免首屏并发加载被误伤；实时流仍使用 120 秒读取超时。
- 观看流畅度取决于家庭宽带上行带宽，不适合长期多路高清同时观看。

## 排查

- 本机隧道：`systemctl --user status frpc`，日志 `~/.config/frp/frpc.log`
- 脚本视角：`./scripts/start-frp.sh --status`
- 服务器：`ssh` 上 kzeng 后 `systemctl status frps`、`nginx -t`、`tail /var/log/frps.log`
- DNS：`dig +short hamster.mitoto.cn` 应返回 `47.97.193.62`
