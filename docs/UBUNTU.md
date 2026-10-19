# Ubuntu 22.04 网关部署步骤

以下命令在你的 Ubuntu 笔记本执行；本次代码交付未执行安装、构建或运行。

## 1. 前提

- 已获取仓库，ESP32-CAM 已烧录、连上 Wi-Fi，并记录了 IP。
- 笔记本能访问摄像头所在局域网，电源持续接入。
- 准备摄像头密钥、一个独立网页访问密码；不需要把密码提供给开发者。

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git rsync
cd ~/projects/esp32-cam-app1
```

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
| `CAMERA_URL` | 摄像头实际地址，如 `http://192.168.1.100`，不加 `/capture` |
| `CAMERA_KEY` | 与 `secrets.h` 完全一致，32–128 位字母／数字，推荐 64 位随机十六进制 |
| `APP_PASSWORD` | 你自定的网页访问密码，至少 12 字符；不是 Tailscale 密码 |
| `SECRET_KEY` | 独立生成的随机会话密钥，至少 32 字符 |
| `CAMERA_NAME` | 网页标题，如 `客厅的小窝` |
| `TARGET_FPS` | 默认 `6`；1–10 的采集目标上限，不保证实际达到 |
| `COOKIE_SECURE` | 本机 HTTP 验证用 `0`；部署 Tailscale Serve HTTPS 后用 `1` |

`.env` 中若有空格、`#` 等字符，请用引号包住值，例如 `APP_PASSWORD='your private password'`。密钥不要使用 `CHANGE_` 示例值。Wi-Fi 密码在板端配置，网关不需要它。

本机启动：

```bash
cd gateway
../.venv/bin/python app.py
```

在这台 Ubuntu 的浏览器打开 `http://127.0.0.1:8080`。输入 `APP_PASSWORD`，点击开始观看。服务只绑定本机，所以此时手机不能直接打开笔记本的局域网 IP。

确认画面、三档分辨率和拍照；终端 `Ctrl+C` 结束。这是开发服务器，长期运行使用下一节 Gunicorn。

## 3. 部署为 systemd 服务

安装位置固定为 `/opt/pet-watch`，运行用户 `petwatch`，服务文件 `/etc/systemd/system/pet-watch.service`。以下为**首次安装步骤**；已有服务时用后面的更新步骤，不重复覆盖配置。

回到仓库根目录：

```bash
cd ~/projects/esp32-cam-app1
sudo useradd --system --home-dir /opt/pet-watch --shell /usr/sbin/nologin petwatch
sudo install -d -o petwatch -g petwatch -m 750 /opt/pet-watch
sudo rsync -a --exclude=.env --exclude=__pycache__ gateway/ /opt/pet-watch/gateway/
sudo cp -a deploy /opt/pet-watch/
sudo chown -R petwatch:petwatch /opt/pet-watch
sudo -u petwatch python3 -m venv /opt/pet-watch/.venv
sudo -u petwatch /opt/pet-watch/.venv/bin/pip install -r /opt/pet-watch/gateway/requirements.txt
sudo -u petwatch cp /opt/pet-watch/gateway/.env.example /opt/pet-watch/gateway/.env
sudo -u petwatch nano /opt/pet-watch/gateway/.env
sudo chmod 600 /opt/pet-watch/gateway/.env
```

在 `/opt/pet-watch/gateway/.env` 填入前面相同的摄像头地址与访问配置。部署 Tailscale Serve 时将 `COOKIE_SECURE=1`。该文件与源码目录下的开发 `.env` 是两个不同文件；修改服务配置要修改 `/opt` 下这一份。

```bash
sudo install -m 644 deploy/pet-watch.service /etc/systemd/system/pet-watch.service
sudo systemctl daemon-reload
sudo systemctl enable --now pet-watch
sudo systemctl status pet-watch --no-pager
```

服务监听 `127.0.0.1:8080`。健康接口只检查网关：

```bash
curl -fsS http://127.0.0.1:8080/healthz
sudo journalctl -u pet-watch -n 80 --no-pager
```

`{"ok":true}` 不代表摄像头在线，还需登录并查看真实画面。`COOKIE_SECURE=1` 时，本机 HTTP 不能保持登录；使用下一节的 HTTPS 地址完成登录验证。

## 4. 配置远程查看

按 [Tailscale 指南](TAILSCALE.md) 安装、登录并启动 Serve。推荐命令为：

```bash
sudo tailscale serve --bg http://127.0.0.1:8080
sudo tailscale serve status
```

使用命令输出的 `https://...ts.net` 地址访问；手机必须开启 Tailscale 且有访问权限。不要把示例域名当作实际地址。

## 5. 持续运行与笔记本电源设置

- Ubuntu 设置 → 电源 → 自动挂起：在接通电源时关闭自动挂起。屏幕熄灭不影响服务。
- 第一轮验收先保持笔记本开盖、通风，确认不会睡眠。
- 合盖行为受 GNOME、电源设置和 logind 配置共同影响；先检查当前行为，再决定是否修改。不要在未经验证时假定合盖后仍运行。
- 检查 Tailscale 管理后台的设备密钥到期时间，在到期前重新认证；若决定关闭该设备的密钥到期，要同时评估设备丢失后的访问风险。

本项目没有替你修改 Ubuntu 的电源、DNS、路由或账号配置。

## 6. 更新与回退

更新前在 Ubuntu 上保留配置和当前源码副本（副本包含密码，权限要限制）：

```bash
sudo cp -a /opt/pet-watch/gateway /opt/pet-watch/gateway.backup
sudo chmod 700 /opt/pet-watch/gateway.backup
cd ~/projects/esp32-cam-app1
git pull --ff-only
sudo systemctl stop pet-watch
sudo rsync -a --exclude=.env --exclude=__pycache__ gateway/ /opt/pet-watch/gateway/
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

若要同时关闭远程入口，先查看 `tailscale serve status`。仅当该设备 Serve 完全由本项目使用时，执行 `sudo tailscale serve reset`；它会清除该设备全部 Serve 配置。

## 故障定位

| 现象 | 排查 |
| --- | --- |
| 服务启动失败 | 查看 journal，检查 `.env` 占位符、字段长度、路径、文件读取权限 |
| 地址已占用 | 确认开发服务器是否仍在 8080 运行 |
| 摄像头超时 | 摄像头 IP、独立电源、Wi-Fi、访客隔离；确认 Ubuntu 可以直接连接摄像头 |
| 401 摄像头错误 | `CAMERA_KEY` 与板端是否一致 |
| 登录反复回到登录页 | `COOKIE_SECURE=1` 必须用 HTTPS；检查地址和浏览器 cookie |
| 手机无法访问，但 Ubuntu 本机正常 | Tailscale 登录／连接、Serve 状态、ACL、电脑是否睡眠 |
| 画面慢 | 先用流畅档，检查上行带宽、Wi-Fi、Tailscale 是否中继；不预设瓶颈来自 ESP32 |
| 暂停后仍有画面更新 | 其他浏览器可能仍在观看，或有一个正在结束的采集请求 |

Gunicorn 必须保持一个 worker。不要直接加 `--workers 4`，否则会有多个独立采集循环争用摄像头。
