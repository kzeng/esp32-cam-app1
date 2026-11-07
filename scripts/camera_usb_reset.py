#!/usr/bin/env python3
"""Release an ESP32-CAM-MB from reset whenever its CH340 USB port appears."""

import argparse
import fcntl
import os
import struct
import sys
import termios
import time
from pathlib import Path


class CameraUsbError(RuntimeError):
    """The configured serial device is absent or is not the expected adapter."""


def usb_identity(device, sys_class_tty=Path("/sys/class/tty")):
    """Return (vendor, product, USB port) for a tty by walking its sysfs parents."""
    tty_device = (sys_class_tty / Path(device).name / "device").resolve(strict=True)
    for parent in (tty_device, *tty_device.parents):
        vendor_file = parent / "idVendor"
        product_file = parent / "idProduct"
        if vendor_file.is_file() and product_file.is_file():
            return (vendor_file.read_text(encoding="ascii").strip().lower(),
                    product_file.read_text(encoding="ascii").strip().lower(),
                    parent.name)
    raise CameraUsbError(f"找不到 {device} 的 USB 身份。")


def pulse_reset(device, vendor, product, usb_port=None, reset_seconds=0.15,
                identity_lookup=usb_identity, opener=os.open, closer=os.close,
                ioctl=fcntl.ioctl, sleep=time.sleep):
    """Release GPIO0, pulse EN low through RTS, then leave both lines released."""
    actual_vendor, actual_product, actual_port = identity_lookup(device)
    expected = (vendor.lower(), product.lower())
    if (actual_vendor, actual_product) != expected:
        raise CameraUsbError(
            f"拒绝操作 {device}：USB {actual_vendor}:{actual_product}，"
            f"预期 {expected[0]}:{expected[1]}。")
    if usb_port and actual_port != usb_port:
        raise CameraUsbError(
            f"拒绝操作 {device}：USB 端口 {actual_port}，预期 {usb_port}。")

    fd = opener(str(device), os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    all_lines = struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS)
    rts = struct.pack("I", termios.TIOCM_RTS)
    try:
        # DTR drives GPIO0 on this download board. Keep it released so the
        # following reset always enters the application, never the bootloader.
        ioctl(fd, termios.TIOCMBIC, all_lines)
        sleep(0.05)
        ioctl(fd, termios.TIOCMBIS, rts)
        sleep(reset_seconds)
        ioctl(fd, termios.TIOCMBIC, all_lines)
        sleep(0.05)
    finally:
        closer(fd)
    return actual_port


def watch(device, vendor, product, usb_port, poll_seconds, retry_seconds,
          exists=None, reset=pulse_reset, sleep=time.sleep, max_cycles=None):
    """Pulse once for each absent-to-present transition, retrying failed opens."""
    released = False
    cycles = 0
    while True:
        present = device.exists() if exists is None else exists()
        if not present:
            released = False
        elif not released:
            try:
                actual_port = reset(device, vendor, product, usb_port)
                print(f"已释放 {device}（USB {vendor}:{product}，端口 {actual_port}）。",
                      flush=True)
                released = True
            except (CameraUsbError, OSError) as error:
                print(f"等待摄像头串口就绪：{error}", file=sys.stderr, flush=True)
                sleep(retry_seconds)
                continue
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            return
        sleep(poll_seconds)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="ESP32-CAM-MB CH340 插入后自动释放 DTR/RTS 并正常启动固件。")
    parser.add_argument("--device", type=Path, default=Path("/dev/ttyUSB0"))
    parser.add_argument("--vendor", default="1a86")
    parser.add_argument("--product", default="7523")
    parser.add_argument("--usb-port", help="可选的固定 USB 拓扑端口，例如 1-2.4")
    parser.add_argument("--watch", action="store_true", help="持续监视拔出/插入")
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--retry-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    if args.poll_seconds < 0.1 or args.retry_seconds < 0.1:
        parser.error("轮询和重试间隔不得小于 0.1 秒。")
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.watch:
        watch(args.device, args.vendor, args.product, args.usb_port,
              args.poll_seconds, args.retry_seconds)
        return 0
    try:
        actual_port = pulse_reset(args.device, args.vendor, args.product, args.usb_port)
    except (CameraUsbError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"已释放 {args.device}（USB {args.vendor}:{args.product}，端口 {actual_port}）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
