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
                    │    ├─ 唯一 JPEG 采集线程
                    │    ├─ 移动检测与事件合并
                    │    └─ SQLite + 私有 JPEG 目录
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
2. 网关启动唯一的采集线程。有人观看时按 `TARGET_FPS` 的目标上限请求 ESP32 `/capture`；无人观看时，第二阶段检测服务按 `MOTION_FPS`（默认 2 FPS）保持低频采集。
3. 摄像头返回一张 JPEG。网关校验类型、大小、JPEG 起止标记，保留最新一帧及该帧的 UTC 抓取时间。
4. 网关将图片以 MJPEG multipart 形式输出给浏览器。多个观看者共享采集，不重复向摄像头取帧；`/api/status` 同步给出该帧时间，页面换算为北京时间显示在画面右上角。实时流本身不重编码，时间只随新帧更新，卡帧时不会继续走秒。
5. 最后一个观看者退出后，若移动检测开启则降到后台检测帧率；检测关闭时才停止新增采集。手动拍照要求取得一张新图片。

这里有意使用摄像头单张 JPEG 接口，而非让每位观看者直接连接板端长连接。这样超时和多观看者管理集中在 Ubuntu；代价是逐帧 HTTP 请求有开销。目标默认 6 FPS，允许 1–10；实际帧率取决于采集和网络速度，不作保证。

分辨率与画质是全局摄像头设置，对所有观看者生效。固件重启回到 VGA；网关不会持久化设置，也不会把旧配置当成已确认设置。网关显示的已确认画质可能在板子单独重启后过时，此时重新选择一次即可。

## 移动检测与事件链路

1. 检测器复用采集线程产生的 JPEG，不额外连接 ESP32。JPEG 解码后缩小为 160×120 灰度图，再执行高斯模糊和背景差分。
2. 只统计网页配置的百分比 ROI；像素变化与面积阈值均可调整。连续 3 帧中至少 2 帧命中才确认运动；近似全画面均匀亮度变化会快速更新背景而不触发事件。
3. 首次确认创建事件；15 秒无确认运动后结束。连续活动不会拆成大量事件。
4. 内存环形缓冲保留最近约 3 秒 JPEG 及各自抓帧时间。每个事件落盘触发前、首次触发、变化峰值三张 JPEG，并在落盘前烧录各自实际抓帧时刻的北京时间水印。
5. SQLite 保存时间、持续时长、峰值分数、查看状态和图片相对路径；图片按 `events/YYYY/MM/DD/event-NNNNNNNN/` 存放。
6. 默认保存 30 天且总图片不超过 2 GB，任一限制达到即按时间删除最旧的完整事件。图片先写临时文件并 `fsync`，再原子改名。
7. 连续采集异常约 30 秒记录一次离线；恢复首帧记录一次恢复。同一离线周期不会重复写状态事件。

运动检测只代表画面发生变化，不等于已识别宠物或人员。2A 不发送外部通知；通知属于 2B，待实景误报稳定后接入。

## 网络与隐私

- 手机通过固定地址 `https://hamster.mitoto.cn` 访问；公网 HTTPS 在 kzeng 云服务器的 nginx 终止，再转发到 frps 映射端口。
- Ubuntu 网关由启动脚本监听 `0.0.0.0:8080`，frpc 将本机 `127.0.0.1:8080` 映射到云服务器。frp 使用 token 验证客户端，具体传输保护取决于 frp 配置。
- ESP32 到 Ubuntu 使用家庭局域网 HTTP，依赖家庭 Wi-Fi 安全；它不属于公网 HTTPS 的加密范围。
- 家庭路由器不需要端口转发，手机也不需要安装专用客户端；公网入口由云服务器、域名和证书共同提供。
- frps 的 `proxyBindAddr` 固定为 `127.0.0.1`，映射端口 `8080` 只供云服务器本机 nginx 使用；公网仅暴露 HTTPS 入口。
- 摄像头接口有密钥校验，但无 HTTPS；不要给摄像头设置公网端口映射。摄像头密钥随 HTTP 请求在局域网传输。
- 所有网页资源随仓库提供，不依赖外部字体、CDN 或第三方统计脚本。
- 服务端不保存连续录像。手动拍照仍由浏览器下载并带抓拍时间水印；移动事件会在 Ubuntu 私有数据目录保存三张带各自抓帧时间水印的 JPEG 和 SQLite 索引。实时 MJPEG 不烧录水印，只由网页叠加最近帧时间。
- 事件图片没有 nginx 静态目录，只能通过登录后的 Flask 接口读取。删除事件会同时删除数据库记录与整个图片目录。
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
| 检测 ROI／阈值 | 不需要 | SQLite `settings` 表，通过网页修改 | 登录后配置 |
| 事件保存期限／上限 | 不需要 | `.env`：`EVENT_RETENTION_DAYS` / `EVENT_QUOTA_MB` | 不需要 |

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
| `GET /api/status` | 当前采集状态、帧序号、最新帧抓取时间、新鲜度、观看连接数及错误 |
| `GET /api/stream` | 登录后读取 MJPEG，最多 6 路连接 |
| `GET /api/snapshot` | 登录后请求一张新图片，烧录抓拍时刻的北京时间水印后作为 JPEG 附件返回 |
| `POST /api/quality` | JSON `{"resolution":"standard"}`，要求会话及 `X-CSRF-Token` |
| `GET /api/flash` | 登录后读取摄像头实际补灯状态 |
| `POST /api/flash` | JSON `{"on":true}`，要求会话及 `X-CSRF-Token`；控制补灯 |
| `GET /events` | 登录后的事件列表、筛选、每页 20 条和三张留图 |
| `GET /api/events/<id>/image/<role>` | 读取 `pre` / `trigger` / `peak` 或列表 `thumb` 私有 JPEG |
| `POST /api/events/<id>/viewed` | 标记事件已查看，要求 CSRF |
| `POST /api/events/<id>/delete` | 删除事件和全部图片，要求 CSRF |
| `POST /api/events/batch` | 单请求批量确认或删除最多 100 个事件，要求 CSRF |
| `GET /motion` | ROI 与检测灵敏度页面 |
| `GET/POST /api/motion-settings` | 读取／保存 ROI、像素阈值和面积阈值；POST 要求 CSRF |
| `GET /healthz` | 仅代表网关 HTTP 服务存活，不代表摄像头在线 |

`/api/status` 状态：idle 表示观看与检测均未要求采集，connecting 表示等待首帧，live 表示网关最近收到新鲜帧，offline 表示采集异常；响应还包含检测是否开启、当前事件和最近变化分数。它不是对手机端播放帧率或全链路延迟的测量。

部署只允许 **一个 Gunicorn worker**，以 16 个线程承接流和普通请求。状态、帧和检测线程在进程内共享，增加 worker 会产生重复采集与重复事件。SQLite 使用 WAL；图片写入目录必须对服务用户可写。静态资源使用版本化长期缓存，事件图片只允许私有短期缓存；HTML、API 与实时流不缓存。公网 nginx 对页面与 API 限速，静态资源和事件图片按 URI 豁免，避免资源并发加载被误判为密集操作。frpc 绑定家庭网卡源地址，frpc/frps 开启 TCP 多路复用，让 10 个逻辑工作连接共用 1 条物理 TCP，并以 15–30 秒保活及时淘汰家庭 NAT 下的失效连接。网页会话有效期 12 小时；已建立的流在请求开始时认证，不逐帧验证，退出／到期通过关闭或重建连接生效。轮换 `SECRET_KEY` 并重启网关可使旧 cookie 失效。

## 官方参考

- [乐鑫摄像头驱动](https://components.espressif.com/components/espressif/esp32-camera)
- [乐鑫 Arduino CameraWebServer 示例](https://github.com/espressif/arduino-esp32/tree/2.0.17/libraries/ESP32/examples/Camera/CameraWebServer)
- [PlatformIO AI Thinker ESP32-CAM](https://docs.platformio.org/en/latest/boards/espressif32/esp32cam.html)
- [Flask 流式响应](https://flask.palletsprojects.com/en/stable/patterns/streaming/)
- [frp](https://github.com/fatedier/frp)
- [nginx 反向代理](https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/)
