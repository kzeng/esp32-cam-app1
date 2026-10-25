# 系统架构与接口

## 硬件与运行边界

第一版针对常见 **AI Thinker ESP32-CAM + OV2640 + PSRAM**。用户已说明是 ESP32-CAM，但尚未确认厂商、芯片丝印和摄像头型号；烧录前必须对照板型。其他 ESP32 摄像头板不能直接套用这组引脚。

```text
5V 稳定电源 ── ESP32-CAM
                    │ 2.4 GHz Wi-Fi / 家庭局域网 HTTP
               家中路由器
                    │ Wi-Fi 或有线
              Ubuntu 22.04 笔记本
                    ├─ Python 网关 0.0.0.0:8080
                    └─ frpc 客户端
                              │ frp 隧道
                    kzeng 云服务器 frps:8080
                              │ 服务器本机反向代理
                    nginx HTTPS:443
                              │ 公网 HTTPS
                         手机浏览器
```

摄像头无需 USB 连到 Ubuntu。USB 转串口只用于烧录／日志；独立运行保留电源、摄像头和 Wi-Fi 即可。Ubuntu 仍需常开，因为第一版由它承接外网查看。独立光源由用户已有设备提供；可在网页手动控制板载 GPIO4 补灯，开机默认关闭，连续点亮最多 1 分钟后自动关闭。不使用 SD 卡（GPIO4 与其引脚复用），补灯状态对所有观看者共用。

## 视频链路

1. 手机登录网页，点击开始观看，请求 `/api/stream`。
2. 网关启动唯一的采集线程，按 `TARGET_FPS` 的目标上限请求 ESP32 `/capture`。
3. 摄像头返回一张 JPEG。网关校验类型、大小、JPEG 起止标记，保留最新一帧。
4. 网关将图片以 MJPEG multipart 形式输出给浏览器。多个观看者共享采集，不重复向摄像头取帧。
5. 最后一个观看者退出后停止新增采集（在途请求最多继续至返回或超时）；手动拍照临时触发一次采集。

这里有意使用摄像头单张 JPEG 接口，而非让每位观看者直接连接板端长连接。这样超时和多观看者管理集中在 Ubuntu；代价是逐帧 HTTP 请求有开销。目标默认 6 FPS，允许 1–10；实际帧率取决于采集和网络速度，不作保证。

分辨率与画质是全局摄像头设置，对所有观看者生效。固件重启回到 VGA；网关不会持久化设置，也不会把旧配置当成已确认设置。网关显示的已确认画质可能在板子单独重启后过时，此时重新选择一次即可。

## 网络与隐私

- 手机通过固定地址 `https://hamster.mitoto.cn` 访问；公网 HTTPS 在 kzeng 云服务器的 nginx 终止，再转发到 frps 映射端口。
- Ubuntu 网关由启动脚本监听 `0.0.0.0:8080`，frpc 将本机 `127.0.0.1:8080` 映射到云服务器。frp 使用 token 验证客户端，具体传输保护取决于 frp 配置。
- ESP32 到 Ubuntu 使用家庭局域网 HTTP，依赖家庭 Wi-Fi 安全；它不属于公网 HTTPS 的加密范围。
- 家庭路由器不需要端口转发，手机也不需要安装专用客户端；公网入口由云服务器、域名和证书共同提供。
- 云服务器上的映射端口 `8080` 当前仍可被公网明文访问。正式入口应使用 HTTPS 域名；若要收紧暴露面，可将 frps 的 `proxyBindAddr` 改为 `127.0.0.1`。
- 摄像头接口有密钥校验，但无 HTTPS；不要给摄像头设置公网端口映射。摄像头密钥随 HTTP 请求在局域网传输。
- 所有网页资源随仓库提供，不依赖外部字体、CDN 或第三方统计脚本。
- 服务端仅把最新帧保留在内存，不保存连续录像或照片文件；拍照由浏览器下载。内存中的最后一张图可能保留到下次更新、错误或进程退出，传输时要求帧仍在新鲜期内。
- 网页照片预览的 blob 保留在当前页面，替换或离开页面时释放；下载后的文件由用户自行管理。

## 配置归属

| 配置 | ESP32-CAM | Ubuntu / 云服务器 | 手机 |
| --- | --- | --- | --- |
| 家庭 Wi-Fi 名称／密码 | `secrets.h` | 操作系统网络配置 | 在外不需要 |
| `CAMERA_KEY` | `secrets.h` | `.env`，同一值 | 不提供给网页 |
| 摄像头 IP | 自动获取并打印 | `CAMERA_URL` | 不需要知道 |
| 网页访问密码 | 不需要 | `APP_PASSWORD` | 登录页面输入 |
| 会话签名密钥 | 不需要 | `SECRET_KEY` | 不手动配置 |
| frp 客户端配置／token | **不需要** | `~/.config/frp/frpc.toml` | 不需要 |
| 公网域名与 HTTPS 证书 | **不需要** | 云服务器 nginx / Let's Encrypt | 只访问固定 HTTPS 地址 |

## 固件接口（端口 80）

全部要求请求头 `X-Camera-Key`，无密钥或错误返回 401。接口不开放 CORS。

| 方法与路径 | 响应 |
| --- | --- |
| `GET /capture` | `image/jpeg`；抓取失败为 503 |
| `GET /status` | 板型标识、运行秒数、RSSI、空闲堆内存、PSRAM 标志 |
| `POST /control?resolution=low` | `low` / `standard` / `high`，成功返回 `{"ok":true}` |
| `GET /flash` | 当前补灯状态 `{"on":false}` |
| `POST /flash?state=on` | `on` / `off`，返回实际状态；点亮 1 分钟后自动关闭 |

默认 VGA（640×480）；low 为 QVGA（320×240），high 为 SVGA（800×600）。摄像头初始化失败会输出串口错误，不提供虚假画面，需修复问题后重启。

## 网关接口（本机端口 8080）

| 方法与路径 | 行为 |
| --- | --- |
| `GET/POST /login` | 网页密码登录；POST 要求 CSRF token |
| `POST /logout` | 清除当前浏览器会话 |
| `GET /` | 登录后进入监控页 |
| `GET /api/status` | 当前采集状态、帧序号、新鲜度、观看连接数及错误 |
| `GET /api/stream` | 登录后读取 MJPEG，最多 6 路连接 |
| `GET /api/snapshot` | 登录后请求一张新图片，作为 JPEG 附件返回 |
| `POST /api/quality` | JSON `{"resolution":"standard"}`，要求会话及 `X-CSRF-Token` |
| `GET /api/flash` | 登录后读取摄像头实际补灯状态 |
| `POST /api/flash` | JSON `{"on":true}`，要求会话及 `X-CSRF-Token`；控制补灯 |
| `GET /healthz` | 仅代表网关 HTTP 服务存活，不代表摄像头在线 |

`/api/status` 状态：idle 表示无采集需求，connecting 表示等待首帧，live 表示网关最近收到新鲜帧，offline 表示采集异常。它不是对手机端播放帧率或全链路延迟的测量。

部署只允许 **一个 Gunicorn worker**，以 16 个线程承接流和普通请求。状态和帧在进程内共享，增加 worker 会产生重复采集。网页会话有效期 12 小时；已建立的流在请求开始时认证，不逐帧验证，退出／到期通过关闭或重建连接生效。第一版没有管理员即时撤销所有会话的界面；轮换 `SECRET_KEY` 并重启网关可使旧 cookie 失效。

## 官方参考

- [乐鑫摄像头驱动](https://components.espressif.com/components/espressif/esp32-camera)
- [乐鑫 Arduino CameraWebServer 示例](https://github.com/espressif/arduino-esp32/tree/2.0.17/libraries/ESP32/examples/Camera/CameraWebServer)
- [PlatformIO AI Thinker ESP32-CAM](https://docs.platformio.org/en/latest/boards/espressif32/esp32cam.html)
- [Flask 流式响应](https://flask.palletsprojects.com/en/stable/patterns/streaming/)
- [frp](https://github.com/fatedier/frp)
- [nginx 反向代理](https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/)
