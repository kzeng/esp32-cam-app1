# 小窝看护 · ESP32-CAM Pet Watch

ESP32-CAM 独立供电，通过家中 Wi-Fi 把宠物画面传给 Ubuntu 22.04 笔记本；手机在外面通过 Tailscale 查看。

**当前为第一版源码交付，尚未构建、运行、烧录或实机验证。按用户要求，本机只编辑代码和文档；构建与部署在另一台 Ubuntu / PlatformIO 环境进行。**

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [三版任务目标](docs/ROADMAP.md) | 第一版、第二版、第三版范围、依赖和验收标准 |
| [系统架构与接口](docs/ARCHITECTURE.md) | 网络拓扑、供电关系、视频链路、配置和接口 |
| [ESP32-CAM 构建与烧录](docs/FIRMWARE.md) | AI Thinker 假设、接线、Wi-Fi、PlatformIO、故障排查 |
| [Ubuntu 部署步骤](docs/UBUNTU.md) | Python 环境、本地启动、systemd、日志和更新 |
| [Tailscale 注册与使用](docs/TAILSCALE.md) | 官方入口、安装、账号关系、费用、隐私、手机外网查看 |
| [开发说明与记录](docs/DEVELOPMENT.md) | 需求决定、文件说明、实施步骤与交付边界 |
| [待执行验收清单](docs/ACCEPTANCE.md) | 在 Ubuntu 和真实硬件上逐项确认 |

## 第一版内容

- 手机网页实时查看、暂停、拍照后下载 JPEG、全屏（浏览器支持时）。
- 三档分辨率：320×240、640×480、800×600；默认 640×480。
- Ubuntu 按需采集，多人观看共享同一采集循环，最多 6 路浏览器连接。
- 画面连接状态、超时提示、自动重连；页面进入后台时暂停采集请求。
- 网页访问密码、会话及 CSRF 防护；摄像头使用独立访问密钥。
- systemd 部署模板；Tailscale Serve 私有 HTTPS 入口。

**未实现：** 连续录像、历史回放、移动检测、通知、声音、对讲、云台、多账号和 AI 识别。它们列入后续路线图，不作为第一版已完成功能。

## 运行关系

```text
独立电源 → ESP32-CAM ──家庭 Wi-Fi── Ubuntu 笔记本
                                      │
                            Tailscale Serve 私有 HTTPS
                                      │
                            手机 Tailscale + 浏览器
```

ESP32-CAM 日常运行无需 USB 连接电脑；烧录和串口调试才需要串口连接。**Tailscale 账号只在 Ubuntu 和手机上登录，摄像头不保存 Tailscale 账号。**

## 从哪里开始

1. 在 Ubuntu 克隆本仓库，阅读 [固件步骤](docs/FIRMWARE.md)，确认板型并配置本地 `firmware/include/secrets.h`。
2. 在 Ubuntu 的 PlatformIO 环境构建、烧录，记录串口打印的摄像头 IP，在路由器中为它保留地址。
3. 按 [Ubuntu 部署步骤](docs/UBUNTU.md) 配置 `gateway/.env`，先在笔记本本机验证。
4. 按 [Tailscale 指南](docs/TAILSCALE.md) 配置手机远程连接。
5. 执行 [验收清单](docs/ACCEPTANCE.md)。性能数值以真实供电、照明和外网测试为准。

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
