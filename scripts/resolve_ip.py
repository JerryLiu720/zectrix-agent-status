#!/usr/bin/env python3
"""zectrix-resolve-ip — 设备 IP 变了也能自动找回来。

顺序：
  1. config.txt 里缓存的 IP（最快）
  2. 本机所在 /24 网段 ping 扫描，用 SDK 的 status 探针逐个确认
找到后写回 config.txt 的 IP= 行。

用法：
    python3 scripts/resolve_ip.py [--config config.txt] [--bin bin/zectrix-status] [--quiet]
退出码：0 找到 / 1 没找到
"""
import argparse
import ipaddress
import os
import re
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor


def probe(binary, ip, timeout=4):
    """设备存在即返回 True（Busy 也算：说明这个 IP 上确实是它）。"""
    try:
        r = subprocess.run([binary, ip], capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return ("电量" in out) or ("Busy" in out) or ("忙碌" in out)
    except Exception:
        return False


def ping(ip):
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "300", ip], capture_output=True, timeout=3)
        return ip if r.returncode == 0 else None
    except Exception:
        return None


def local_prefix():
    try:
        out = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, timeout=3).stdout.strip()
        if out:
            net = ipaddress.ip_network(out + "/24", strict=False)
            return str(net.network_address).rsplit(".", 1)[0]
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip.rsplit(".", 1)[0]
    except Exception:
        return None


def read_cached(path):
    try:
        for line in open(path, encoding="utf-8"):
            if line.startswith("IP="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def write_cached(path, ip):
    lines, found = [], False
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except Exception:
        pass
    for i, l in enumerate(lines):
        if l.startswith("IP="):
            lines[i] = f"IP={ip}"
            found = True
    if not found:
        lines.append(f"IP={ip}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.txt"))
    ap.add_argument("--bin", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "zectrix-status"))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if not os.access(a.bin, os.X_OK):
        if not a.quiet:
            print(f"找不到探针 {a.bin}", file=sys.stderr)
        return 1

    cached = read_cached(a.config)
    if cached and probe(a.bin, cached):
        if not a.quiet:
            print(cached)
        return 0

    prefix = local_prefix()
    if not prefix:
        return 1
    hosts = [f"{prefix}.{i}" for i in range(1, 255)]
    alive = []
    with ThreadPoolExecutor(max_workers=64) as ex:
        for r in ex.map(ping, hosts):
            if r:
                alive.append(r)

    for ip in alive:
        if probe(a.bin, ip):
            write_cached(a.config, ip)
            if not a.quiet:
                print(ip)
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
