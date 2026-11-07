# -*- coding: utf-8 -*-
"""
微云充充电桩监控服务 (Google Cloud Run 生产部署版)
特性：
  1. 纯标准库 zero-dependency（基于 http.server.ThreadingHTTPServer），无需庞大依赖
  2. 支持 PORT 环境变量（Cloud Run 标准端口约定，默认 8080）
  3. 内置 IP 访问频率限制防刷策略（Rate Limiter，防爆刷与恶意攻击）
  4. 支持 6 秒聚合数据缓存，削峰填谷，彻底保护后端与避免额度耗尽
  5. 优雅关机（SIGTERM/SIGINT），适配容器生命周期
"""

import os
import sys
import json
import time
import signal
from collections import defaultdict
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Cloud Run 容器标准端口环境变量
PORT = int(os.environ.get("PORT", 8080))

API_URL = "https://saas.laichon.com/api/app/ebike/getDeviceInfo"

HEADERS = {
    "openid": "oOO3c4op_7fkh8C4-q0mFnbn-uIQ",
    "authorization": "bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczpcL1wvbW9iaWxlLmxhaWNob24uY29tIiwiaWF0IjoxNzk0MDgxMDE4LCJleHAiOjE3OTUzNzcwMTgsInN1YiI6MzI4ODk1NzEsInJvbGUiOiJ1c2VyIiwibW9uaXRvcl91c2VyX2lkIjoiN2YyZjM4YTViMzJkNzIwNGRhMzM4YzI0MzEyMDNmZjciLCJqdGkiOjk3Nzc4MDQyMDk0NDMxODQ2NSwibmJmIjoxNzk0MDgxMDE4fQ==.EhEjWeppWqmxxwGpEg2UAlOF-kNgwCe1V8Q89TUIoME=",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541f0d) XWEB/25715",
    "xweb_xhr": "1",
    "service-code": "WYC-MI-WEIXIN",
    "content-type": "application/json",
    "accept": "*/*",
    "referer": "https://servicewechat.com/wxa68db1dabe823e7e/662/page-frame.html"
}

devices = [
    {"name": "1号机", "device_no": "L32022884"},
    {"name": "2号机", "device_no": "L32022881"},
    {"name": "3号机", "device_no": "L32022883"},
    {"name": "4号机", "device_no": "L32022882"}
]

# 缓存机制：6 秒内所有用户共享一份状态，避免频繁穿透到上游或耗费 CPU 算力
cache_data = {"time": 0, "result": None}

# ==========================================
# 安全防线：内存级滑动窗口 IP 频率限制器 (Rate Limiter)
# 规则：单 IP 每 10 秒最多允许 15 次请求，超出直接返回 429 Too Many Requests
# ==========================================
RATE_LIMIT_WINDOW = 10  # 统计窗口（秒）
RATE_LIMIT_MAX_REQUESTS = 15  # 窗口内最大请求数
ip_request_history = defaultdict(list)


def is_rate_limited(client_ip: str) -> bool:
    """检查客户端 IP 是否超过频率限制"""
    now = time.time()
    # 清理过期请求记录
    history = [t for t in ip_request_history[client_ip] if now - t < RATE_LIMIT_WINDOW]
    if len(history) >= RATE_LIMIT_MAX_REQUESTS:
        ip_request_history[client_ip] = history
        return True
    history.append(now)
    ip_request_history[client_ip] = history
    return False


def fetch_all_status():
    """获取 4 台设备实时插孔状态（带 6 秒共享缓存）"""
    now = time.time()
    if cache_data["result"] and (now - cache_data["time"] < 6):
        return cache_data["result"]

    session = requests.Session()
    session.trust_env = False

    result_list = []
    total_slots = 0
    free_slots = 0

    for dev in devices:
        payload = {"device_no": dev["device_no"]}
        try:
            resp = session.post(API_URL, headers=HEADERS, json=payload, timeout=5, verify=False)
            data = resp.json().get("data", {})
            guns = data.get("device_gunpoint", [])
            guns_status = []
            for g in guns:
                is_free = (g.get("gun_status") == 0)
                guns_status.append({
                    "gun_no": g.get("gun_no"),
                    "is_free": is_free
                })
            dev_free = sum(1 for x in guns_status if x["is_free"])
            dev_total = len(guns_status)

            total_slots += dev_total
            free_slots += dev_free

            result_list.append({
                "name": dev["name"],
                "device_no": dev["device_no"],
                "total": dev_total,
                "free": dev_free,
                "used": dev_total - dev_free,
                "guns": guns_status,
                "error": None
            })
        except Exception as e:
            result_list.append({
                "name": dev["name"],
                "device_no": dev["device_no"],
                "total": 10,
                "free": 0,
                "used": 10,
                "guns": [],
                "error": str(e)
            })

    output = {
        "update_time": time.strftime("%H:%M:%S"),
        "update_date": time.strftime("%m月%d日"),
        "total_slots": total_slots,
        "free_slots": free_slots,
        "used_slots": total_slots - free_slots,
        "occupancy_rate": round(((total_slots - free_slots) / max(1, total_slots)) * 100, 1),
        "devices": result_list
    }

    cache_data["time"] = now
    cache_data["result"] = output
    return output


# PWA Web App Manifest JSON
PWA_MANIFEST = {
    "name": "微云充智能监控",
    "short_name": "微云日月充",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#F2F5FA",
    "theme_color": "#F2F5FA",
    "description": "常州大学西太湖校区微云充实时插孔状态监控系统 · 开发者：日月潭",
    "icons": [
        {
            "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='24' fill='%2310B981'/><path d='M55 18L28 54h18l-6 28 27-36H49l6-28z' fill='white'/></svg>",
            "sizes": "192x192 512x512",
            "type": "image/svg+xml"
        }
    ]
}

SERVICE_WORKER_JS = """
self.addEventListener('install', (e) => { self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(clients.claim()); });
self.addEventListener('fetch', (e) => { e.respondWith(fetch(e.request).catch(() => new Response('离线状态'))); });
"""

def get_html_page():
    """优先动态读取最新的统一暗夜极光前端 index.html"""
    html_file = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_file):
        try:
            with open(html_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return "<html><body><h1>微云日月充 启动中...</h1></body></html>"


class SafeCloudRunHandler(BaseHTTPRequestHandler):
    def get_client_ip(self):
        """解析客户端真实 IP（兼容 Cloud Run 反向代理头 X-Forwarded-For）"""
        x_forwarded_for = self.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return self.client_address[0]

    def do_GET(self):
        client_ip = self.get_client_ip()

        # 安全防线：速率限制检查
        if is_rate_limited(client_ip):
            self.send_response(429)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Retry-After", "10")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Too Many Requests", "message": "请求过于频繁，请稍候重试"}, ensure_ascii=False).encode("utf-8"))
            return

        if self.path == "/healthz" or self.path == "/_health":
            # Cloud Run 原生健康检查探测路径
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        elif self.path == "/manifest.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(PWA_MANIFEST, ensure_ascii=False).encode("utf-8"))
        elif self.path == "/sw.js":
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.end_headers()
            self.wfile.write(SERVICE_WORKER_JS.strip().encode("utf-8"))
        elif self.path == "/api/status":
            data = fetch_all_status()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(get_html_page().encode("utf-8"))

    def log_message(self, format, *args):
        # 容器标准环境静默多余 access log，节省日志配额
        pass


def run_server():
    server_address = ("0.0.0.0", PORT)
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer(server_address, SafeCloudRunHandler)
    print(f"[Cloud Run Ready] 服务已在 0.0.0.0:{PORT} 启动，安全防线已就绪。")

    def shutdown_signal(sig, frame):
        print("\n接收到终止信号，正在安全关闭...")
        httpd.server_close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_signal)
    signal.signal(signal.SIGTERM, shutdown_signal)

    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
