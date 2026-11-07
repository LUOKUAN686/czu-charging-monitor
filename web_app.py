# -*- coding: utf-8 -*-
"""
微云充充电桩移动端 PWA 应用 (苹果 iOS 清爽毛玻璃风格)
模块：web_app.py
功能：
  1. 纯原生零依赖 (Python 内置 http.server)，即开即用
  2. 极致苹果 iOS 毛玻璃质感设计 (Apple Clean Glass)，自适应全面屏与桌面 PWA 安装
  3. 实时查询 4 台设备 40 个插孔状态，高亮空闲插孔，带轻触动效与一键刷新
"""

import sys
import json
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import requests
import urllib3

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PORT = 8080
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

cache_data = {"time": 0, "result": None}


def fetch_all_status():
    """获取 4 台设备实时插孔状态（带 6 秒本地缓存防刷）"""
    now = time.time()
    if cache_data["result"] and (now - cache_data["time"] < 6):
        return cache_data["result"]

    session = requests.Session()
    session.trust_env = False  # 直连公网，不受代理环境干扰

    result_list = []
    total_slots = 0
    free_slots = 0

    for dev in devices:
        payload = {"device_no": dev["device_no"]}
        try:
            resp = session.post(API_URL, headers=HEADERS, json=payload, timeout=8, verify=False)
            data = resp.json().get("data", {})
            guns = data.get("device_gunpoint", [])
            guns_status = []
            for g in guns:
                # 经现场验证校准：gun_status == 0 为空闲可用插孔
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
    "short_name": "充电监控",
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


# 极简 Service Worker，满足 PWA 离线安装能力
SERVICE_WORKER_JS = """
self.addEventListener('install', (e) => { self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(clients.claim()); });
self.addEventListener('fetch', (e) => { e.respondWith(fetch(e.request).catch(() => new Response('离线状态'))); });
"""


# 苹果 iOS 毛玻璃现代 UI 模板
HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>微云充 · 实时插孔看板</title>
    
    <!-- PWA 配置支持 -->
    <link rel="manifest" href="/manifest.json">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="default">
    <meta name="apple-mobile-web-app-title" content="充电监控">
    <link rel="apple-touch-icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='24' fill='%2310B981'/><path d='M55 18L28 54h18l-6 28 27-36H49l6-28z' fill='white'/></svg>">
    <meta name="theme-color" content="#F2F5FA">

    <style>
        :root {
            --bg-gradient: linear-gradient(135deg, #F0F4F8 0%, #E8EDF5 50%, #F5F7FA 100%);
            --glass-bg: rgba(255, 255, 255, 0.72);
            --glass-border: rgba(255, 255, 255, 0.85);
            --glass-shadow: 0 8px 32px rgba(15, 23, 42, 0.05);
            
            --text-primary: #1C1C1E;
            --text-secondary: #8E8E93;
            --text-tertiary: #AEAEB2;

            --apple-green: #34C759;
            --apple-green-light: rgba(52, 199, 89, 0.12);
            --apple-green-glow: rgba(52, 199, 89, 0.28);
            
            --apple-gray-busy: #F2F2F7;
            --apple-gray-txt: #8E8E93;
            --apple-blue: #007AFF;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif;
        }

        body {
            background: var(--bg-gradient);
            min-height: 100vh;
            color: var(--text-primary);
            padding: calc(env(safe-area-inset-top, 20px) + 12px) 16px calc(env(safe-area-inset-bottom, 20px) + 20px);
            max-width: 520px;
            margin: 0 auto;
            position: relative;
            overflow-x: hidden;
        }

        /* 顶部装饰光晕 */
        .ambient-glow {
            position: fixed;
            width: 280px;
            height: 280px;
            background: radial-gradient(circle, rgba(52, 199, 89, 0.15) 0%, rgba(0, 122, 255, 0.08) 50%, transparent 70%);
            top: -60px;
            right: -60px;
            z-index: 0;
            pointer-events: none;
            filter: blur(40px);
        }

        .main-wrapper {
            position: relative;
            z-index: 1;
        }

        /* 顶部导航与操作栏 */
        header {
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            margin-bottom: 18px;
            padding: 0 4px;
        }
        .header-title-box h1 {
            font-size: 25px;
            font-weight: 700;
            letter-spacing: -0.5px;
            color: var(--text-primary);
        }
        .creator-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            background: rgba(0, 122, 255, 0.08);
            color: var(--apple-blue);
            font-size: 11px;
            font-weight: 600;
            padding: 3px 9px;
            border-radius: 12px;
            margin-bottom: 5px;
            border: 1px solid rgba(0, 122, 255, 0.15);
        }
        .badge-dot {
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: var(--apple-blue);
        }
        .refresh-pill {
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 7px 14px;
            font-size: 13px;
            font-weight: 600;
            color: var(--apple-blue);
            box-shadow: 0 4px 12px rgba(0, 122, 255, 0.08);
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: transform 0.15s ease, background 0.15s;
        }
        .refresh-pill:active {
            transform: scale(0.94);
            background: rgba(255, 255, 255, 0.95);
        }

        /* iOS 核心统计卡片 */
        .hero-metric-card {
            background: var(--glass-bg);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid var(--glass-border);
            border-radius: 24px;
            padding: 22px;
            margin-bottom: 22px;
            box-shadow: var(--glass-shadow);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .metric-info h2 {
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-secondary);
            font-weight: 600;
            margin-bottom: 6px;
        }
        .metric-num-wrap {
            display: flex;
            align-items: baseline;
            gap: 6px;
        }
        .huge-num {
            font-size: 42px;
            font-weight: 800;
            letter-spacing: -1px;
            color: var(--apple-green);
        }
        .huge-unit {
            font-size: 16px;
            color: var(--text-secondary);
            font-weight: 600;
        }
        .metric-sub {
            font-size: 12px;
            color: var(--text-tertiary);
            margin-top: 4px;
        }

        /* 环形进度条组件 */
        .ring-container {
            position: relative;
            width: 76px;
            height: 76px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .ring-svg {
            transform: rotate(-90deg);
        }
        .ring-circle-bg {
            fill: none;
            stroke: #E5E5EA;
            stroke-width: 7;
        }
        .ring-circle-fill {
            fill: none;
            stroke: var(--apple-green);
            stroke-width: 7;
            stroke-linecap: round;
            transition: stroke-dashoffset 0.8s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .ring-percent {
            position: absolute;
            font-size: 15px;
            font-weight: 700;
            color: var(--text-primary);
        }

        /* 分区标题 */
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            padding: 0 4px;
        }
        .section-title {
            font-size: 15px;
            font-weight: 700;
            color: var(--text-primary);
            letter-spacing: -0.2px;
        }
        .section-tag {
            font-size: 12px;
            color: var(--text-secondary);
        }

        /* 设备卡片 */
        .device-card {
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 18px;
            margin-bottom: 14px;
            box-shadow: var(--glass-shadow);
            transition: transform 0.2s ease;
        }
        .device-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 14px;
        }
        .dev-title-wrap {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .dev-name {
            font-size: 17px;
            font-weight: 700;
            color: var(--text-primary);
            letter-spacing: -0.3px;
        }
        .dev-badge-no {
            background: rgba(142, 142, 147, 0.12);
            color: var(--text-secondary);
            font-size: 11px;
            font-weight: 600;
            padding: 2px 7px;
            border-radius: 6px;
        }
        .dev-status-badge {
            font-size: 12px;
            font-weight: 600;
            padding: 4px 10px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        .status-badge-free {
            background: var(--apple-green-light);
            color: var(--apple-green);
        }
        .status-badge-busy {
            background: var(--apple-gray-busy);
            color: var(--apple-gray-txt);
        }
        .status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
        }
        .dot-green {
            background: var(--apple-green);
            box-shadow: 0 0 6px var(--apple-green);
        }
        .dot-gray {
            background: #C7C7CC;
        }

        /* 插孔九宫格 */
        .slots-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 8px;
        }
        .slot-btn {
            background: var(--apple-gray-busy);
            border-radius: 14px;
            padding: 10px 4px;
            text-align: center;
            border: 1px solid transparent;
            transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
            position: relative;
        }
        .slot-free {
            background: #FFFFFF;
            border-color: rgba(52, 199, 89, 0.45);
            box-shadow: 0 4px 14px var(--apple-green-glow);
            cursor: pointer;
        }
        .slot-free:active {
            transform: scale(0.92);
        }
        .slot-num {
            font-size: 16px;
            font-weight: 700;
            color: #8E8E93;
            letter-spacing: -0.3px;
        }
        .slot-free .slot-num {
            color: var(--apple-green);
        }
        .slot-label {
            font-size: 11px;
            margin-top: 2px;
            font-weight: 600;
            color: #AEAEB2;
        }
        .slot-free .slot-label {
            color: var(--apple-green);
        }

        /* 底部引导栏与署名 */
        .pwa-tip {
            margin-top: 24px;
            text-align: center;
            padding: 14px;
            background: rgba(255, 255, 255, 0.5);
            border-radius: 14px;
            border: 1px solid rgba(255, 255, 255, 0.6);
            font-size: 12px;
            color: var(--text-secondary);
            line-height: 1.6;
        }
        .pwa-tip strong {
            color: var(--text-primary);
        }
        .app-footer {
            text-align: center;
            font-size: 11px;
            color: var(--text-tertiary);
            margin-top: 18px;
            padding-bottom: 10px;
            line-height: 1.6;
        }
        .app-footer strong {
            color: var(--text-secondary);
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="ambient-glow"></div>
    <div class="main-wrapper">
        <header>
            <div class="header-title-box">
                <div class="creator-badge">
                    <span class="badge-dot"></span>
                    <span>开发者 · 日月潭</span>
                </div>
                <h1>常州大学西太湖校区</h1>
            </div>
            <button class="refresh-pill" onclick="refreshData()">
                <span id="refresh-icon">🔄</span>
                <span id="update-time">--:--:--</span>
            </button>
        </header>

        <!-- 顶部核心指标卡片 (Apple Activity 风格) -->
        <div class="hero-metric-card">
            <div class="metric-info">
                <h2>当前全区可用车位</h2>
                <div class="metric-num-wrap">
                    <span class="huge-num" id="free-total">--</span>
                    <span class="huge-unit">/ <span id="total-slots">40</span> 孔可用</span>
                </div>
                <div class="metric-sub" id="status-hint">正在拉取最新状态...</div>
            </div>
            <div class="ring-container">
                <svg class="ring-svg" width="76" height="76">
                    <circle class="ring-circle-bg" cx="38" cy="38" r="30"></circle>
                    <circle class="ring-circle-fill" id="ring-fill" cx="38" cy="38" r="30" stroke-dasharray="188.4" stroke-dashoffset="188.4"></circle>
                </svg>
                <div class="ring-percent" id="ring-txt">--%</div>
            </div>
        </div>

        <div class="section-header">
            <span class="section-title">机台插孔详情 (0 ~ 9 号)</span>
            <span class="section-tag">绿灯即为空位，速充</span>
        </div>

        <div id="devices-container"></div>

        <div class="pwa-tip">
            💡 <strong>添加到手机主屏幕秒变原生 App：</strong><br>
            苹果 iPhone 点击 Safari 底部<strong>「分享」</strong>➔ <strong>「添加到主屏幕」</strong><br>
            安卓手机点击浏览器右上角<strong>「设置」</strong>➔ <strong>「添加到桌面」</strong>
        </div>

        <footer class="app-footer">
            常州大学西太湖校区 · 微云充智能监控系统<br>
            Designed & Developed by <strong>日月潭</strong> · 数据实时同步
        </footer>
    </div>

    <script>
        let isRefreshing = false;

        function updateUI(data) {
            document.getElementById("update-time").innerText = data.update_time;
            document.getElementById("free-total").innerText = data.free_slots;
            document.getElementById("total-slots").innerText = data.total_slots;

            // 提示文案
            const hintElem = document.getElementById("status-hint");
            if (data.free_slots > 0) {
                hintElem.innerHTML = `🟢 发现 <strong>${data.free_slots}</strong> 个空位，可直接带充电器前往`;
                hintElem.style.color = "var(--apple-green)";
            } else {
                hintElem.innerHTML = `🈵 全区插孔已占满，建议稍后刷新捡漏`;
                hintElem.style.color = "var(--apple-gray-txt)";
            }

            // 更新能量环 (剩余可用率)
            const freeRate = data.total_slots > 0 ? (data.free_slots / data.total_slots) : 0;
            const circumference = 2 * Math.PI * 30; // 188.4
            const offset = circumference - (freeRate * circumference);
            document.getElementById("ring-fill").style.strokeDashoffset = offset;
            document.getElementById("ring-txt").innerText = Math.round(freeRate * 100) + "%";

            // 渲染设备卡片
            const container = document.getElementById("devices-container");
            container.innerHTML = "";

            data.devices.forEach(dev => {
                const isFree = dev.free > 0;
                const card = document.createElement("div");
                card.className = "device-card";

                let slotsHtml = "";
                dev.guns.forEach(g => {
                    if (g.is_free) {
                        slotsHtml += `
                            <div class="slot-btn slot-free" onclick="copySlotHint('${dev.name}', ${g.gun_no})">
                                <div class="slot-num">${g.gun_no}号</div>
                                <div class="slot-label">空闲</div>
                            </div>
                        `;
                    } else {
                        slotsHtml += `
                            <div class="slot-btn">
                                <div class="slot-num">${g.gun_no}号</div>
                                <div class="slot-label">占用</div>
                            </div>
                        `;
                    }
                });

                card.innerHTML = `
                    <div class="device-header">
                        <div class="dev-title-wrap">
                            <span class="dev-name">${dev.name}</span>
                            <span class="dev-badge-no">${dev.device_no}</span>
                        </div>
                        <div class="dev-status-badge ${isFree ? 'status-badge-free' : 'status-badge-busy'}">
                            <span class="status-dot ${isFree ? 'dot-green' : 'dot-gray'}"></span>
                            <span>${isFree ? `空闲 ${dev.free} 个孔` : '满载充电'}</span>
                        </div>
                    </div>
                    <div class="slots-grid">
                        ${slotsHtml}
                    </div>
                `;
                container.appendChild(card);
            });
        }

        async function refreshData() {
            if (isRefreshing) return;
            isRefreshing = true;
            const icon = document.getElementById("refresh-icon");
            icon.style.transition = "transform 0.6s ease";
            icon.style.transform = "rotate(360deg)";

            try {
                const resp = await fetch("/api/status");
                const data = await resp.json();
                updateUI(data);
                if (navigator.vibrate) navigator.vibrate(25); // 苹果/安卓微震动反馈
            } catch (e) {
                console.error(e);
            } finally {
                setTimeout(() => {
                    icon.style.transform = "rotate(0deg)";
                    isRefreshing = false;
                }, 600);
            }
        }

        function copySlotHint(devName, slotNo) {
            alert(`已为你锁定：${devName} 的【${slotNo}号孔】为空闲状态，请前往插枪！`);
        }

        // 注册 Service Worker 满足 PWA 标准
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/sw.js').catch(() => {});
        }

        // 首次加载数据
        refreshData();

        // 每隔 20 秒静默更新一次
        setInterval(refreshData, 20000);
    </script>
</body>
</html>
"""


class ApplePWAHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/manifest.json":
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
            self.wfile.write(HTML_PAGE.encode("utf-8"))

    def log_message(self, format, *args):
        # 保持控制台清爽
        pass


def run_web_server():
    server_address = ("0.0.0.0", PORT)
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer(server_address, ApplePWAHandler)
    print("\n" + "=" * 65)
    print(" 🍏 苹果 iOS 毛玻璃风格 PWA 移动端应用已就绪！")
    print(f" 👉 电脑本地访问: http://127.0.0.1:{PORT}")
    print(f" 👉 同一 WiFi 手机访问: http://你的电脑局域网IP:{PORT}")
    print(" 👉 配合 cpolar 开启穿透: 运行 `cpolar http 8080` 生成公网链接")
    print("=" * 65 + "\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb 服务已安全关闭。")


if __name__ == "__main__":
    run_web_server()
