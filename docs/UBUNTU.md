# Ubuntu 22.04 网关部署步骤

以下命令在你的 Ubuntu 笔记本执行；按实际部署路径调整，已有配置不要直接覆盖。

## 1. 前提

- 已获取仓库，ESP32-CAM 已烧录新固件、通过 [热点配网](FIRMWARE.md) 连上 Wi-Fi，并发布 `pet-camera.local`。
- 笔记本能访问摄像头所在局域网，电源持续接入。
- 准备摄像头密钥、一个独立网页访问密码；不需要把密码提供给开发者。

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git rsync avahi-daemon avahi-utils libnss-mdns
sudo systemctl enable --now avahi-daemon
cd ~/projects/esp32-cam-app1
```

### 验证 mDNS 名称解析

```bash
avahi-resolve-host-name -4 pet-camera.local
getent ahostsv4 pet-camera.local
```

两者都应返回摄像头当前的局域网 IP。第二条走普通应用使用的系统解析路径，不能只以 Avahi 专用工具成功作为验收依据。若 Avahi 成功而 `getent` 失败，检查 `/etc/nsswitch.conf` 的 `hosts:` 行是否包含 `mdns4_minimal`；常见配置为 `hosts: files mdns4_minimal [NOTFOUND=return] dns`，但不要直接覆盖现有行中的其他解析模块。已有可用 systemd-resolved mDNS 配置时可沿用，不必再叠加一套解析服务。

摄像头和 Ubuntu 必须位于可交换局域网多播的网络中；访客隔离、不同 VLAN、防火墙或 Mihomo TUN 可能阻断 UDP 5353 多播。不要为此把 UDP 5353 暴露到公网，不要在 `/etc/hosts` 写死摄像头地址。`.local` 只解决 Ubuntu 到摄像头这一段，不影响手机的公网地址。可用不带密钥的请求进一步验证 HTTP 可达性：

```bash
curl --noproxy '*' --connect-timeout 3 --max-time 8 -i http://pet-camera.local/status
```

预期返回 `401 Unauthorized`，说明名称解析和 HTTP 已通；不是认证成功，也不代表已经能取图。

## 2. 本地配置与首次运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r gateway/requirements.txt
cp gateway/.env.example gateway/.env
python3 -c 'import secrets; print(secrets.token_hex(32))'
nano gateway/.env
chmod 600 gateway/.env
```

把新生成的随机值用于 `SECRET_KEY`。配置说明：

| 字段 | 填写内容 |
| --- | --- |
| `CAMERA_URL` | 默认 `http://pet-camera.local`，与固件 `CAMERA_HOSTNAME` 一致，不加 `/capture`；仍兼容 IP 地址 |
| `CAMERA_KEY` | 与 `secrets.h` 完全一致，32–128 位字母／数字，推荐 64 位随机十六进制 |
| `APP_PASSWORD` | 你自定的网页访问密码，至少 12 字符 |
| `SECRET_KEY` | 独立生成的随机会话密钥，至少 32 字符 |
| `CAMERA_NAME` | 网页标题，如 `客厅的小窝` |
| `TARGET_FPS` | 默认 `6`；1–10 的采集目标上限，不保证实际达到 |
| `COOKIE_SECURE` | 本机 HTTP 验证用 `0`；通过正式 HTTPS 域名使用时设 `1` |
| `MOTION_ENABLED` | `1` 开启后台移动检测；临时排查时可设 `0` |
| `MOTION_FPS` | 无观看者时检测帧率，默认 `2`，不得高于 `TARGET_FPS` |
| `MOTION_QUIET_SECONDS` | 多少秒无活动后结束当前事件，默认 `15` |
| `EVENT_RETENTION_DAYS` | 图片保存天数，默认 `30` |
| `EVENT_QUOTA_MB` | 事件图片总上限，默认 `2048` MB |
| `DATA_DIR` | SQLite 与事件图片目录，默认相对 `gateway` 的 `data` |

`.env` 中若有空格、`#` 等字符，请用引号包住值，例如 `APP_PASSWORD='your private password'`。密钥不要使用 `CHANGE_` 示例值。Wi-Fi 密码在板端配置，网关不需要它。

已有部署迁移时：先烧录新固件、确认上述两种解析及 HTTP 检查通过，再只修改实际运行网关的 `.env` 中 `CAMERA_URL`，最后重启对应网关进程／服务。修改仓库示例不会更新已有配置。网关不自行扫描网段或永久缓存解析结果；采集失败后清空 HTTP 连接池、退避重试，由系统重新解析名称。系统 mDNS 缓存更新可能需要时间，不承诺 IP 变化后立即恢复。

本机启动：

```bash
cd gateway
../.venv/bin/python app.py
```

在这台 Ubuntu 的浏览器打开 `http://127.0.0.1:8080`。输入 `APP_PASSWORD`，确认实时画面、事件页和检测设置页。开发服务器只绑定本机。

确认画面、三档分辨率和拍照；终端 `Ctrl+C` 结束。这是开发服务器，长期运行使用下一节 Gunicorn。

## 3. 部署为 systemd 服务

安装位置固定为 `/opt/pet-watch`，运行用户 `petwatch`，服务文件 `/etc/systemd/system/pet-watch.service`。以下为**首次安装步骤**；已有服务时用后面的更新步骤，不重复覆盖配置。

回到仓库根目录：

```bash
cd ~/projects/esp32-cam-app1
sudo useradd --system --home-dir /opt/pet-watch --shell /usr/sbin/nologin petwatch
sudo install -d -o petwatch -g petwatch -m 750 /opt/pet-watch
sudo rsync -a --exclude=.env --exclude=data --exclude=__pycache__ gateway/ /opt/pet-watch/gateway/
sudo cp -a deploy /opt/pet-watch/
sudo chown -R petwatch:petwatch /opt/pet-watch
sudo -u petwatch python3 -m venv /opt/pet-watch/.venv
sudo -u petwatch /opt/pet-watch/.venv/bin/pip install -r /opt/pet-watch/gateway/requirements.txt
sudo -u petwatch cp /opt/pet-watch/gateway/.env.example /opt/pet-watch/gateway/.env
sudo -u petwatch install -d -m 700 /opt/pet-watch/gateway/data
sudo -u petwatch nano /opt/pet-watch/gateway/.env
sudo chmod 600 /opt/pet-watch/gateway/.env
```

在 `/opt/pet-watch/gateway/.env` 填入前面相同的摄像头地址与访问配置。通过 `https://hamster.mitoto.cn` 使用时将 `COOKIE_SECURE=1`。该文件与源码目录下的开发 `.env` 是两个不同文件；修改服务配置要修改 `/opt` 下这一份。

```bash
sudo install -m 644 deploy/pet-watch.service /etc/systemd/system/pet-watch.service
sudo systemctl daemon-reload
sudo systemctl enable --now pet-watch
sudo systemctl status pet-watch --no-pager
```

systemd 模板监听 `127.0.0.1:8080`；仓库的 `start-frp.sh` 为现有 frpc 链路监听 `0.0.0.0:8080`。两者都只允许一个 Gunicorn worker。健康接口只检查网关：

```bash
curl -fsS http://127.0.0.1:8080/healthz
sudo journalctl -u pet-watch -n 80 --no-pager
```

`{"ok":true}` 不代表摄像头在线，还需登录并查看真实画面。`COOKIE_SECURE=1` 时，本机 HTTP 不能保持登录；使用下一节的 HTTPS 地址完成登录验证。

## 4. 配置远程查看

按 [frp 指南](FRP.md) 确认本机 `frpc`、kzeng 上的 `frps` 和 nginx HTTPS 在线：

```bash
./scripts/start-frp.sh --status
```

手机直接访问 `https://hamster.mitoto.cn`，无需安装额外客户端。若网关尚未启动，可运行 `./scripts/start-frp.sh`；脚本会复用已运行的 frpc 用户服务。

## 5. 持续运行与笔记本电源设置

- Ubuntu 设置 → 电源 → 自动挂起：在接通电源时关闭自动挂起。屏幕熄灭不影响服务。
- 第一轮验收先保持笔记本开盖、通风，确认不会睡眠。
- 合盖行为受 GNOME、电源设置和 logind 配置共同影响；先检查当前行为，再决定是否修改。不要在未经验证时假定合盖后仍运行。
- 定期用 `./scripts/start-frp.sh --status` 确认网关、frpc 和公网 HTTPS 三段均正常。

本项目没有替你修改 Ubuntu 的电源、DNS、路由或账号配置。

## 6. 更新与回退

更新前在 Ubuntu 上保留配置和当前源码副本（副本包含密码，权限要限制）：

```bash
sudo cp -a /opt/pet-watch/gateway /opt/pet-watch/gateway.backup
sudo chmod 700 /opt/pet-watch/gateway.backup
cd ~/projects/esp32-cam-app1
git pull --ff-only
sudo systemctl stop pet-watch
sudo rsync -a --exclude=.env --exclude=data --exclude=__pycache__ gateway/ /opt/pet-watch/gateway/
sudo chown -R petwatch:petwatch /opt/pet-watch/gateway
sudo -u petwatch /opt/pet-watch/.venv/bin/pip install -r /opt/pet-watch/gateway/requirements.txt
sudo systemctl start pet-watch
sudo systemctl status pet-watch --no-pager
```

首次更新前确认 `gateway.backup` 尚不存在；后续使用不同备份名称，避免 `cp` 嵌套旧备份。该备份只覆盖源码和配置，不固定 Python 依赖；需要完整可重现回退时，同时保存虚拟环境的依赖版本清单。依赖使用兼容范围，非完整锁文件。

源码回退（根据实际备份名称替换）：

```bash
sudo systemctl stop pet-watch
sudo rsync -a /opt/pet-watch/gateway.backup/ /opt/pet-watch/gateway/
sudo chown -R petwatch:petwatch /opt/pet-watch/gateway
sudo systemctl start pet-watch
```

## 7. 停止

```bash
sudo systemctl disable --now pet-watch
```

若要同时关闭远程入口，停止本机 `frpc` 用户服务；不要在未确认其他映射用途时停用云服务器 frps。

## 故障定位

| 现象 | 排查 |
| --- | --- |
| 服务启动失败 | 查看 journal，检查 `.env` 占位符、字段长度、路径、文件读取权限 |
| 地址已占用 | 确认开发服务器是否仍在 8080 运行 |
| 摄像头超时 | `getent ahostsv4 pet-camera.local`、独立电源、Wi-Fi、访客隔离；确认 Ubuntu 可以直接连接摄像头 |
| 401 摄像头错误 | `CAMERA_KEY` 与板端是否一致 |
| 登录反复回到登录页 | `COOKIE_SECURE=1` 必须用 HTTPS；检查地址和浏览器 cookie |
| 手机无法访问，但 Ubuntu 本机正常 | `start-frp.sh --status`、frpc 日志、kzeng 上 frps/nginx、电脑是否睡眠 |
| 画面慢 | 先用流畅档，检查 ESP32 Wi-Fi、家庭上行、frp 链路；不预设瓶颈来自 ESP32 |
| 没有移动事件 | 检查 `MOTION_ENABLED=1`、事件页状态、ROI 是否覆盖活动区、面积阈值是否过高 |
| 事件过多 | 缩小 ROI、提高像素／面积阈值；先观察灯光、窗帘和摄像头抖动 |
| 服务报数据目录只读 | 确认 data 目录属于 `petwatch`，服务文件含 `ReadWritePaths=/opt/pet-watch/gateway/data` |
| 暂停后仍有画面更新 | 其他浏览器可能仍在观看，或有一个正在结束的采集请求 |

Gunicorn 必须保持一个 worker。不要直接加 `--workers 4`，否则会有多个独立采集循环争用摄像头。
