# Tailscale：注册、下载、费用、隐私与大陆连接验证

官方资料核对日期：2026-10-19。套餐和网络可用性可能变化，安装时以官网与实测为准。

## 1. 它在本系统中的作用

Tailscale 让外面的手机安全连接家里的 Ubuntu。它承接远程连接；本项目的 Python 网关负责摄像头画面、网页和拍照。

```text
外面的手机（Tailscale 客户端 + 浏览器）
                   │ 加密连接
Ubuntu（Tailscale Serve → 127.0.0.1:8080）
                   │ 家庭 Wi-Fi / 局域网 HTTP
              ESP32-CAM
```

**ESP32-CAM 不安装 Tailscale，不需要 Tailscale 账号、密码、验证码或 auth key。** 不要把 Tailscale 登录凭据写到固件，也不需要发给开发者。

## 2. 注册和下载入口

| 用途 | 官方入口 |
| --- | --- |
| 注册／登录 | https://login.tailscale.com/start |
| 管理设备和权限 | https://login.tailscale.com/admin/machines |
| 各平台下载 | https://tailscale.com/download |
| Android | https://tailscale.com/download/android |
| iPhone / iPad | https://tailscale.com/download/ios |
| Linux / Ubuntu 安装说明 | https://tailscale.com/docs/install/linux |
| 价格 | https://tailscale.com/pricing |

按登录页面当前提供的身份验证方式创建个人账号。手机与 Ubuntu 加入同一个个人 tailnet，最简单的方式是用同一账号分别登录。若与家人共享，后续可以邀请独立账号并设置权限，不要共享账号密码。

## 3. Ubuntu 22.04 安装与登录

官方提供 Ubuntu 22.04（Jammy）软件包；命令在你的 Ubuntu 执行。

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale status
tailscale ip -4
```

第一条命令会下载并执行官方安装脚本，添加相应软件源、安装客户端。也可以使用[官方软件包页面](https://pkgs.tailscale.com/stable/)的 Ubuntu 22.04 手动 apt 步骤。

`tailscale up` 输出认证链接，在浏览器完成登录。登录链接、临时认证令牌不能提交到仓库。`tailscale ip -4` 通常返回 `100.x.x.x` 地址，它是私有组网地址，不是向公网开放的 IP。

Tailscale 在 Linux 由 `tailscaled` 后台服务运行：

```bash
systemctl status tailscaled --no-pager
```

安装脚本或登录页面在当前网络打不开时，先停止后续假设并记录失败阶段；能下载客户端不等于能成功登录，能登录也不等于视频链路稳定。

## 4. 手机安装

1. 从上述官方 Android / iOS 下载页面进入对应商店或官方分发渠道。
2. 登录与 Ubuntu 相同的账号，按系统提示允许建立 VPN 连接。
3. 在客户端确认 Ubuntu 已出现在设备列表中。
4. 先保持手机 Wi-Fi 开启，确认基本连接；之后关闭 Wi-Fi、改用移动数据验证真正的外网连接。

手机系统通常限制同时启用的 VPN 服务数量，与其他 VPN 应用可能冲突。不要把客户端已打开当成已连接，应检查客户端状态。

## 5. 建立私有 HTTPS 网页入口

先按 [Ubuntu 部署步骤](UBUNTU.md) 启动网关，确认监听 `127.0.0.1:8080`，生产 `.env` 中设置 `COOKIE_SECURE=1`。

```bash
sudo tailscale serve --bg http://127.0.0.1:8080
sudo tailscale serve status
```

首次使用如果提示启用 HTTPS 等条件，按终端给出的官方授权链接处理。Serve 需要 tailnet HTTPS 配置，受访问控制规则限制。使用命令输出的实际 `https://设备名.tailnet名.ts.net` 地址；不要猜测地址。

手机开启 Tailscale，在浏览器打开这个 HTTPS 地址，再输入本项目的 `APP_PASSWORD`。这两个登录用途不同：

| 登录位置 | 凭据 | 目的 |
| --- | --- | --- |
| Tailscale App / Ubuntu 登录网页 | Tailscale 身份账号 | 允许设备加入私有网络 |
| 小窝看护登录页面 | 自己在 Ubuntu `.env` 设置的 `APP_PASSWORD` | 允许查看摄像头 |

第一版不启用子网路由，也不需要在路由器上转发端口。**使用 Serve，不配置公开入口 Funnel。** 如果该笔记本已有 Serve 配置，先执行 `tailscale serve status`，确认本项目不会覆盖现有根路径；必要时换设备或设计专用端口后再配置。

启用 HTTPS 证书时，设备域名可能出现在公开的证书透明度日志中。不要在设备名中包含家庭地址等敏感内容；域名可见并不表示私有服务可以被公网访问。参见[官方 HTTPS 证书说明](https://tailscale.com/docs/how-to/set-up-https-certificates)。

## 6. 是否免费

截至核对日期，官网 **Personal** 计划标价 $0，适用于个人非商业用途，列出最多 6 位用户、个人用户设备不限数量，并另有 tagged / ephemeral 资源额度。你的一台 Ubuntu 加一部手机属于该家庭使用场景，当前不需要购买付费套餐。

这不是免除家中宽带、手机数据流量或自行购买中继服务器的费用。不要把“免费”理解为官方承诺无限视频带宽或任何网络下的可用性。使用个人套餐前在管理界面确认实际选择的计划；自定义域名注册的组织可能进入试用流程，不能把企业试用期当成个人套餐。

来源：[官方价格页](https://tailscale.com/pricing)。本文不承诺未来价格不变，也不自动开启任何付费附加功能。

## 7. 隐私保护与边界

根据[官方安全说明](https://tailscale.com/security)：

- Tailscale 设备之间使用 WireGuard 端到端加密。
- 私钥保留在对应设备上，协调服务交换公钥和连接信息。
- 即使通过 DERP 中继，转发的也是加密数据，官方说明不能解密视频内容。

根据[隐私政策](https://tailscale.com/privacy-policy)，服务仍会收集账号及连接相关元数据，例如设备名、操作系统、IP、公钥、访问时间和连接统计。因此有传输隐私保护，不代表匿名或完全不收集数据，也不是“绝对安全”的保证。

本项目的具体边界：

- 加密连接终点是 Ubuntu，Ubuntu 本身能看到并处理画面。
- ESP32 到 Ubuntu 的 HTTP 走家庭局域网，该段依赖 Wi-Fi 安全，不受 Tailscale 加密覆盖。
- 第一版不把视频上传云端保存；网页照片由手机自行下载。
- 账号被盗、手机丢失、Ubuntu 被入侵、误配访问规则仍会影响隐私。个人身份账号建议启用多因素认证，丢失设备后及时撤销授权。
- 不使用 Tailscale 的 Aperture 或 PAM 录制功能；本文加密说明针对普通设备连接，不能泛化为其所有产品都不处理内容。

## 8. 中国大陆能不能用

**可以作为待验证方案，但不预先保证在中国大陆所有运营商、地区或时段都稳定可用。** 本次官方资料核对没有获得针对用户所在地的可用性保证，也没有在用户实际家庭网络上做测试。

根据[官方连接类型说明](https://tailscale.com/docs/reference/connection-types)：连接会尝试升级为直连；UDP 受阻或复杂 NAT 等条件可能阻止直连。需要中继时，中继可达性也影响结果。[官方中继故障文档](https://tailscale.com/docs/reference/messages/client/no-derp-connection)说明，中继连接失败可能来自网络、防火墙或域名／端口受阻。

对本系统的工程判断是：手机与家庭电脑若能直连，通常更适合实时视频；如果只能走延迟较高或不稳定的中继，画面可能卡顿。具体能否看、延迟多少，必须实测，不能由“安装成功”推断。

### 最小实测步骤

1. Ubuntu 与手机先安装、登录；手机关闭 Wi-Fi、使用移动数据，保持 Tailscale 开启。
2. Ubuntu 上查看：

   ```bash
   tailscale status
   tailscale netcheck
   ```

3. 从 `tailscale status` 找到手机设备名称或 Tailscale IP，再替换命令中的占位符：

   ```bash
   tailscale ping PHONE_NAME_OR_TAILSCALE_IP
   ```

4. 记录实际输出：是否建立 direct 连接，是否持续走 DERP，中继区域及延迟。`netcheck` 主要检查运行该命令的 Ubuntu 一侧，不代表手机网络已被完整测试。
5. 手机访问 Serve 的 HTTPS 地址，先选流畅画质，观看至少 10–15 分钟；记录卡顿、断开和重连情况。再试标准画质，并在不同时间段重复。
6. 截图或分享日志前，遮盖邮箱、公网 IP、设备名及其他隐私。

**通过标准：** 注册／登录可完成，手机使用移动数据能稳定打开页面和看图，质量与延迟满足本人需求。只显示设备在线，不算视频验收通过。

若不通过，先区分登录服务、DNS／证书、直连、中继和摄像头局域网问题。之后可以评估可控的国内中继／其他远程入口；选型要重新考虑成本、权限和部署条件，不自动购买服务器或改动现有网络。本项目摄像头 HTTP 接口与 Ubuntu 网关独立于 Tailscale，后续可以替换远程连接方式。

## 9. 退出与撤销

- 手机可随时关闭 Tailscale 连接；Ubuntu 仍可在家庭网络中读取摄像头。
- 管理后台可以移除丢失或不再使用的设备。
- 网页退出只结束当前浏览器登录，不会退出 Tailscale 账号。
- 若关闭入口，先查看 `tailscale serve status`；`sudo tailscale serve reset` 会清空该设备全部 Serve 配置，只在确认不影响其他服务时执行。
