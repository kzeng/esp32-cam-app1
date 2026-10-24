# ESP32-CAM：Ubuntu / PlatformIO 构建与烧录

本文命令由用户在另一台 Ubuntu 上执行。本次开发机器不执行构建、烧录或服务启动。

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

## 3. 配置 Wi-Fi 和摄像头密钥

```bash
cp firmware/include/secrets.example.h firmware/include/secrets.h
python3 -c 'import secrets; print(secrets.token_hex(32))'
nano firmware/include/secrets.h
```

将刚生成的 64 位十六进制随机值填入 `CAMERA_KEY`；后续 Ubuntu `.env` 使用同一个值。

```cpp
#define WIFI_SSID "你的2.4GHz Wi-Fi名称"
#define WIFI_PASSWORD "你的Wi-Fi密码"
#define CAMERA_KEY "你生成的随机十六进制密钥"
```

字符串中若有双引号或反斜杠，按 C++ 字符串规则转义。不要把实际配置复制到公开文档、聊天或提交中。`.gitignore` 已排除 `secrets.h`。Tailscale 账号和登录密码不写入这里。

没有 `secrets.h` 时源码仍允许编译，但固件会打印配置提示并停止初始化；示例 `CHANGE_` 密钥不会运行。

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

5. 记录 `Camera ready: http://192.168.x.x`。在路由器 DHCP 设置中为摄像头保留该地址；不需要在固件中硬编码 IP。

串口权限不足时：

```bash
sudo usermod -aG dialout "$USER"
```

退出并重新登录 Ubuntu 后生效。不要以长期 `sudo pio` 替代正确的设备权限。

## 6. 脱离电脑独立运行

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
