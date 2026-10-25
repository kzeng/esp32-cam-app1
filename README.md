# 小窝看护 · ESP32-CAM Pet Watch

ESP32-CAM 独立供电，通过家中 Wi-Fi 把宠物画面传给 Ubuntu 22.04 笔记本；手机在外面通过 frp 隧道和云服务器上的 nginx HTTPS 入口查看。

**当前已在本机 Ubuntu 构建、烧录，并验证拍照与补灯开关接口；补灯自动关闭、远程访问和长期运行仍需进一步验收。**

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [三版任务目标](docs/ROADMAP.md) | 第一版、第二版、第三版范围、依赖和验收标准 |
| [系统架构与接口](docs/ARCHITECTURE.md) | 网络拓扑、供电关系、视频链路、配置和接口 |
| [ESP32-CAM 构建与烧录](docs/FIRMWARE.md) | AI Thinker 假设、接线、Wi-Fi、PlatformIO、故障排查 |
| [Ubuntu 部署步骤](docs/UBUNTU.md) | Python 环境、本地启动、systemd、日志和更新 |
| [frp 手机外网查看](docs/FRP.md) | 本机一键启动、手机地址、限制与安全说明 |
| [开发说明与记录](docs/DEVELOPMENT.md) | 需求决定、文件说明、实施步骤与交付边界 |
| [待执行验收清单](docs/ACCEPTANCE.md) | 在 Ubuntu 和真实硬件上逐项确认 |

## 第一版内容

- 手机网页实时查看、暂停、拍照后下载 JPEG、全屏（浏览器支持时）。
- 网页手动开启／关闭板载补灯（GPIO4），最长点亮 1 分钟后自动关闭。
- 三档分辨率：320×240、640×480、800×600；默认 640×480。
- Ubuntu 按需采集，多人观看共享同一采集循环，最多 6 路浏览器连接。
- 画面连接状态、超时提示、自动重连；页面进入后台时暂停采集请求。
- 网页访问密码、会话及 CSRF 防护；摄像头使用独立访问密钥。
- systemd 部署模板；frp 隧道和云端 nginx HTTPS 入口。

**未实现：** 连续录像、历史回放、移动检测、通知、声音、对讲、云台、多账号和 AI 识别。它们列入后续路线图，不作为第一版已完成功能。

## 运行关系

```text
独立电源 → ESP32-CAM ──家庭 Wi-Fi── Ubuntu 笔记本
                                      │
                                frpc → frps
                                      │
                         云端 nginx HTTPS → 手机浏览器
```

ESP32-CAM 日常运行无需 USB 连接电脑；烧录和串口调试才需要串口连接。摄像头只连接家庭 Wi-Fi，不保存 frp 或云服务器凭据；手机也无需安装额外客户端。

## 从哪里开始

1. 在 Ubuntu 克隆本仓库，阅读 [固件步骤](docs/FIRMWARE.md)，确认板型并配置本地 `firmware/include/secrets.h`。
2. 在 Ubuntu 的 PlatformIO 环境构建、烧录，记录串口打印的摄像头 IP，在路由器中为它保留地址。
3. 按 [Ubuntu 部署步骤](docs/UBUNTU.md) 配置 `gateway/.env`，先在笔记本本机验证。
4. 按 [frp 指南](docs/FRP.md) 确保网关与隧道在线，再通过固定 HTTPS 地址远程连接。
5. 执行 [验收清单](docs/ACCEPTANCE.md)。性能数值以真实供电、照明和外网测试为准。

外网入口走 frp（云服务器 kzeng 上的 frps + nginx HTTPS），可从仓库根目录运行
`./scripts/start-frp.sh`，自动启动尚未运行的网关并确保隧道在线，打印手机 HTTPS 地址；
`--status` 仅查询状态。隧道由 systemd 用户服务 `frpc` 常驻，脚本会优先复用。

## 源码结构

```text
firmware/                 PlatformIO / Arduino ESP32 固件
  include/secrets.example.h
  src/main.cpp
gateway/                  Ubuntu Python 网关
  app.py                  登录、API、MJPEG 输出
  camera.py               按需采集、共享帧、重连
  templates/              登录与监控页面
  static/                 无外部 CDN 的 CSS / JavaScript
  .env.example            网关本地配置示例
deploy/pet-watch.service  systemd 服务模板
docs/                     架构、开发、部署、路线图、验收
```

`.gitignore` 排除了实际密码配置、Python 环境、构建产物和照片目录。提交之前仍应检查暂存区，示例文件中只填占位符。
