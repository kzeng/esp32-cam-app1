# ESP32-CAM：Ubuntu / PlatformIO 构建与烧录

本文包含构建与烧录操作说明；构建成功不代表已烧录，烧录会中断摄像头运行。

## 1. 确认硬件

- 本项目目标是 **AI Thinker ESP32-CAM、OV2640、带 PSRAM**；不是所有带 ESP32 的摄像头板都兼容。
- 确认摄像头排线安装牢固，并按开发板标识确认 5V、GND、U0R、U0T、IO0。
- ESP32-CAM 使用 2.4 GHz 家庭 Wi-Fi。Ubuntu 可以使用同一路由器的有线或无线连接，两者必须能互访；访客网络隔离可能阻止连接。
- 日常运行使用稳定的 5V 电源接板上 **5V / GND**（或匹配的供电底座）；可从额定 5V / 1A 或更高的可靠电源开始，最终按实测确认。不要把 5V 接到 3V3。
- 串口信号必须使用 **3.3V TTL 电平**。USB 转串口的供电电压与 TX/RX 电平不是同一概念，连接前核实转换器说明。
- 不默认 USB 转串口的弱供电能稳定驱动摄像头；使用独立电源时共地，避免两个电源输出直接并接。

AI Thinker 固件引脚：

| 信号 | GPIO |
| --- | --- |
| D0–D7 | 5、18、19、21、36、39、34、35 |
| XCLK / PCLK | 0 / 22 |
| VSYNC / HREF | 25 / 23 |
| SCCB SDA / SCL | 26 / 27 |
| PWDN / RESET | 32 / -1 |
| 板载补灯 | 4，开机关闭，可由网页控制，1 分钟后自动关闭 |

来源：[乐鑫 camera_pins.h 的 AI_THINKER 分支](https://github.com/espressif/arduino-esp32/blob/2.0.17/libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h)。板型不匹配时先修改引脚和 PlatformIO board 配置，不要盲目烧录。

## 2. 获取源码与准备 PlatformIO

```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/kzeng/esp32-cam-app1.git
cd esp32-cam-app1
```

在已配置好的 PlatformIO 环境中使用 `pio`。若尚未安装，可用独立虚拟环境：

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git
python3 -m venv ~/.venvs/platformio
~/.venvs/platformio/bin/pip install platformio
source ~/.venvs/platformio/bin/activate
pio --version
```

`firmware/platformio.ini` 固定 `espressif32@6.10.0`、`board=esp32cam`、Arduino 框架（该平台版本对应 Arduino ESP32 2.0.17）。首次构建需联网下载工具链，后续可复用缓存。

## 3. 配置摄像头密钥（Wi-Fi 通过网页配置）

```bash
cp firmware/include/secrets.example.h firmware/include/secrets.h
python3 -c 'import secrets; print(secrets.token_hex(32))'
nano firmware/include/secrets.h
```

将刚生成的 64 位十六进制随机值填入 `CAMERA_KEY`；后续 Ubuntu `.env` 使用同一个值。

```cpp
#define CAMERA_HOSTNAME "pet-camera"
#define CAMERA_KEY "你生成的随机十六进制密钥"
```

字符串中若有双引号或反斜杠，按 C++ 字符串规则转义。不要把实际配置复制到公开文档、聊天或提交中。`.gitignore` 已排除 `secrets.h`。frp、云服务器和网页登录凭据都不写入固件。

没有 `secrets.h` 时源码仍允许编译，但固件会打印配置提示并停止初始化；示例 `CHANGE_` 密钥不会运行。

`CAMERA_HOSTNAME` 可省略，默认 `pet-camera`；为兼容 DHCP 主机名限制，仅允许 1–32 位小写字母、数字和连字符，首尾不能是连字符，不加 `.local`。同一局域网有多块摄像头时分别设置唯一名称，并同步修改各自网关的 `CAMERA_URL`。固件设置 DHCP 主机名，同时在获得 IP 后启动 mDNS、发布 `_http._tcp` 的 80 端口；断线后停止发布，重连或检测到 IP 变化后重新发布，启动失败每 15 秒重试。不发布密钥，也不启用 OTA。

Wi-Fi 名称和密码不再从 `secrets.h` 读取；旧文件中的 `WIFI_SSID` / `WIFI_PASSWORD` 不会用于连接，建议删除。`CAMERA_HOSTNAME` 只是初始默认名称，网页保存的设备名优先。`CAMERA_KEY` 仍在本地固件配置中，本次没有实现摄像头密钥的动态配对。

## 4. 构建（在 Ubuntu 上）

```bash
cd ~/projects/esp32-cam-app1/firmware
pio run
```

构建成功后，产物位于 `firmware/.pio/build/esp32cam/`。本仓库不提交生成的 `.bin`，成功构建也不代表已经烧录或摄像头已经能工作。

## 5. 连接串口并烧录

使用带自动下载功能的 ESP32-CAM USB 底座时，按底座说明进入下载模式。使用普通 USB 转串口时：

| USB 转串口 | ESP32-CAM |
| --- | --- |
| TX（3.3V 电平） | U0R / RX |
| RX（3.3V 电平） | U0T / TX |
| GND | GND |
| 电源 | 按前述供电方案接 5V，避免重复供电 |

1. 断电，将 IO0 接 GND；上电／复位进入下载模式。
2. 查看串口，按实际端口替换示例中的 `/dev/ttyUSB0`：

   ```bash
   pio device list
   pio run -t upload --upload-port /dev/ttyUSB0
   ```

3. 烧录结束后断电，**移除 IO0 与 GND 的连接**，再上电／复位。IO0 也是摄像头时钟脚，日常运行不能继续短接 GND。
4. 查看启动日志：

   ```bash
   pio device monitor --port /dev/ttyUSB0 --baud 115200
   ```

5. 首次启动先按下一节配网；成功后确认日志出现 `Camera ready: http://192.168.x.x` 和 `mDNS ready: http://pet-camera.local`。按 [Ubuntu 部署说明](UBUNTU.md) 验证名称解析，将网关配置为 `CAMERA_URL=http://pet-camera.local`。IP 用于诊断，无需在固件中硬编码，也不再要求路由器做 DHCP 地址保留；地址保留仍可作为可选措施。

串口权限不足时：

```bash
sudo usermod -aG dialout "$USER"
```

退出并重新登录 Ubuntu 后生效。不要以长期 `sudo pio` 替代正确的设备权限。

## 6. 首次配网、更换网络与恢复

首次启动或没有有效网络配置时，设备开启 `PetCam-Setup-<设备标识>` 热点。热点密码是每台设备独立生成并保存在 NVS 的随机值，不是摄像头密钥，也不是统一默认密码。

1. 在本地串口监视器中发送 `wifi-info`（以换行结束），读取配网热点名称和密码。串口波特率 115200；PlatformIO 交互监视器可开启本地回显并使用换行发送。不要将输出粘贴到聊天、工单或公开日志；可将密码保存到自己的密码管理器或设备标签。
2. 手机连接该热点，提示“无互联网”时保持连接。
3. 手动打开 `http://192.168.4.1:8081`，填写目标 2.4 GHz Wi-Fi 的 SSID、密码和设备名。手机页面自动异步扫描附近网络，SSID 文本框可手动输入或展开列表选择，支持输入筛选及刷新；按 RSSI 从强到弱排列，同名网络保留最强项，最多显示 30 个。显示加密状态和信号强度；隐藏 SSID 可手动输入，不强制弹窗。SSID 最多 32 字节（中文按 UTF-8 字节计算），密码为空或 8–63 字节；空密码只用于开放网络。不支持企业 Wi-Fi、网页登录认证网络或 64 位原始 PSK。
4. 提交后查看状态页。试连最多 30 秒，获取非零 IP 并保持连接约 3 秒后写入配置。成功状态为 `connected`，约 8 秒后热点关闭、设备回到正常 STA 模式；手机需重新连接家庭网络。
5. 错误密码、连接超时、保存错误均显示失败，允许返回重试；旧的已保存配置不会被普通试连覆盖。取消或窗口到期会关闭热点并重新连接已保存网络。每次配网窗口最长 10 分钟；没有配置且超时后不会反复开放热点，发送 `wifi-setup` 可重新开启。

网络配置按版本保存在 `pet-network` NVS 命名空间，以双槽保存、回读校验后切换生效标记。驱动试连使用 RAM，不自动保存候选密码。普通重启会恢复已保存配置；常规烧录通常保留 NVS，擦除整片 Flash 则清除配置和配网热点密码。NVS 未启用加密，不承诺抵抗物理读出或所有存储硬件故障；不要把设备交给不可信人员。

### 更换 Wi-Fi

串口命令均以换行结束，不回显或接受目标 Wi-Fi 密码：

| 命令 | 功能 |
| --- | --- |
| `wifi-info` | 仅在本地串口显示配网热点名称和密码 |
| `wifi-ap-password <password>` | 本地修改并保存热点密码，8–63 位可打印 ASCII；若热点已开启则重开，断开现有连接。不回显密码，测试后应换强密码 |
| `wifi-setup` | 开启配网窗口，不删除旧配置 |
| `wifi-cancel` | 取消配网，返回已保存网络 |
| `wifi-forget CONFIRM` | 清除网络配置并开启配网；不清除摄像头密钥或热点密码 |

在线时也可向摄像头 `POST /network/setup`，使用已有 `X-Camera-Key` 认证开启热点；该接口仅开启配网，不接受或返回 Wi-Fi 密码。第一版不添加网关网页按钮。离线时使用本地串口恢复，不依赖旧路由器或旧 IP，也不新增 GPIO 按键。网络暂时断开时每约 30 秒重试已保存配置，不会自动开启热点。

### 安全与网络限制

- 配网 HTTP 仅绑定热点地址的 8081 端口，修改操作需要当前窗口的随机令牌；正常局域网接口不能访问表单。配网时不转发端口、不开放到公网。
- 热点接入密码提供无线链路保护，页面本身是 HTTP；这不是端到端 HTTPS。持有热点密码的人员应视为有权重新配网，窗口结束或成功后停止配网服务。
- 固定配网子网为 `192.168.4.0/24`，目标网络如使用相同子网可能产生路由冲突，应先更换目标网络子网；不能承诺这种情况下试连可靠。
- AP+STA 试连可能切换无线信道，手机可能短暂断开热点，需重新连接。实际手机兼容性按验收清单验证。
- 如目标为手机热点，Ubuntu 网关也必须能访问该网络的摄像头；客户端隔离、组播受限可能影响 HTTP 或 mDNS。仅摄像头切换网络不会让原网络的 Ubuntu 自动跨网访问。
- 首次升级到本版本不会自动导入旧固件硬编码的 Wi-Fi 或驱动保存的凭据，需要通过配网热点配置一次；升级前准备好串口和密钥备份。

## 7. 脱离电脑独立运行

```text
烧录时：Ubuntu ── USB 转串口 ── ESP32-CAM（另按需要供电）
日常：  5V 电源 ── ESP32-CAM ── Wi-Fi ── 路由器 ── Ubuntu
```

移除串口连接后，摄像头只接电源即可。Ubuntu 通过网络获取画面，不通过 USB 传输视频。

## 常见问题

| 现象 | 检查方向 |
| --- | --- |
| 上传时无法连接 | 实际串口、权限、IO0 下载模式、复位时机、RX/TX 是否交叉 |
| 上传后一直等待下载 | IO0 是否仍接 GND，是否已重新上电 |
| `PSRAM unavailable` | 板型／PSRAM 硬件／供电；当前版本明确要求 PSRAM |
| `Camera init failed` | 板型引脚、排线、摄像头模组、电源 |
| 反复复位或 brownout | 电源能力、线材压降、接地；固件未屏蔽 brownout 检测 |
| Wi-Fi 连不上 | 2.4 GHz、密码、信号、路由器隔离设置 |
| 网关提示密钥不匹配 | 重新核对板端 `CAMERA_KEY` 和 Ubuntu `.env`，修改固件需重新烧录 |
| 图像方向不合适 | 当前没有网页旋转／镜像控制；调整安装方向或在固件初始化时设置 sensor 的 vflip / hmirror |

若环境温度高或长时间运行不稳定，记录供电、RSSI、复位日志和温度后再判断原因；不要把网络超时直接当成电源故障。
