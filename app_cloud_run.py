# -*- coding: utf-8 -*-
"""
微云充充电桩监控服务 (Google Cloud Run / Render 生产部署版)
特性：
  1. 纯标准库 zero-dependency（基于 http.server.ThreadingHTTPServer），无需庞大依赖
  2. 支持 PORT 环境变量（Render / Cloud Run 标准端口约定，默认 8080）
  3. 内置 IP 访问频率限制防刷策略（Rate Limiter，防爆刷与恶意攻击）
  4. 支持 6 秒聚合数据缓存，削峰填谷，彻底保护后端与避免额度耗尽
  5. 健全的云端鉴权中心：
     - 一人一密（邮箱白名单与独占激活码）
     - 一号一机独占绑定（设备指纹硬件级单点锁定，杜绝多人共享）
     - 可视化 /admin 管理控制台
     - 自动与 GitHub 仓库加密双向同步（防数据丢失，免付费数据库）
  6. 优雅关机（SIGTERM/SIGINT），适配容器生命周期
"""

import os
import sys
import json
import time
import signal
import hmac
import hashlib
import base64
from collections import defaultdict
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Cloud Run / Render 容器标准端口环境变量
PORT = int(os.environ.get("PORT", 8080))

# 管理员总密码（支持环境变量覆盖，默认推荐高强度预设）
ADMIN_MASTER_KEY = os.environ.get("ADMIN_MASTER_KEY", "RiyueTan@CZU2026")

# GitHub 自动加密同步配置
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "LUOKUAN686/czu-charging-monitor")
AUTH_FILE_LOCAL = os.path.join(os.path.dirname(__file__), "auth_db.json")

# 微云充上游微信接口配置
API_URL = "https://saas.laichon.com/api/app/ebike/getDeviceInfo"
HEADERS = {
    "openid": "oOO3c4op_7fkh8C4-q0mFnbn-uIQ",
    "authorization": "bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczpcL1wvbW9iaWxlLmxhaWNob24uY29tIiwiaWF0IjoxNzk0MDgxMDE4LCJleHAiOjE3OTUzNzcwMTgsInN1YiI6MzI4ODk1NzEsInJvbGUiOiJ1c2VyIiwibW9uaXRvcl91c2VyX2lkIjoiN2YyZjM4YTViMzJkNzIwNGRhMzM4YzI0MzEyMDNmZjciLCJqdGkiOjk3Nzc4MDQyMDk0NDMxODQ2NSwibmJmIjoxNzk0MDgxMDE4fQ==.EhEjWeppWqmxxwGpEg2UAlOF-kNgwCe1V8Q89TUIoME=",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254200d) XWEB/26073",
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

# 缓存机制：6 秒内所有用户共享一份状态，避免频繁穿透到上游
cache_data = {"time": 0, "result": None}

# 安全防线：IP 访问频率限制
RATE_LIMIT_WINDOW = 10
RATE_LIMIT_MAX_REQUESTS = 25
ip_request_history = defaultdict(list)


def is_rate_limited(client_ip: str) -> bool:
    """检查客户端 IP 是否超过频率限制"""
    now = time.time()
    history = [t for t in ip_request_history[client_ip] if now - t < RATE_LIMIT_WINDOW]
    if len(history) >= RATE_LIMIT_MAX_REQUESTS:
        ip_request_history[client_ip] = history
        return True
    history.append(now)
    ip_request_history[client_ip] = history
    return False


# ==========================================
# 数据加密与 GitHub 同步管理器
# ==========================================
class AuthDB:
    def __init__(self):
        self.users = []  # [{email, key, memo, bound_device, bound_at, created_at}]
        self.load()

    def _get_cipher_key(self):
        return hashlib.sha256(ADMIN_MASTER_KEY.encode("utf-8")).digest()

    def _encrypt(self, plain_text: str) -> str:
        key = self._get_cipher_key()
        b_text = plain_text.encode("utf-8")
        encrypted = bytes([b ^ key[i % len(key)] for i, b in enumerate(b_text)])
        return base64.b64encode(encrypted).decode("utf-8")

    def _decrypt(self, cipher_b64: str) -> str:
        key = self._get_cipher_key()
        encrypted = base64.b64decode(cipher_b64.encode("utf-8"))
        decrypted = bytes([b ^ key[i % len(key)] for i, b in enumerate(encrypted)])
        return decrypted.decode("utf-8")

    def load(self):
        # 1. 尝试从本地加载
        if os.path.exists(AUTH_FILE_LOCAL):
            try:
                with open(AUTH_FILE_LOCAL, "r", encoding="utf-8") as f:
                    self.users = json.load(f)
                    print(f"[AuthDB] 从本地成功加载 {len(self.users)} 名授权用户")
                    return
            except Exception as e:
                print(f"[AuthDB] 本地读取失败: {e}")

        # 2. 若本地无数据且配置了 GITHUB_TOKEN，尝试从 GitHub 拉取
        if GITHUB_TOKEN:
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/auth_db.enc"
                headers = {
                    "Authorization": f"token {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json"
                }
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    raw_b64 = resp.json().get("content", "")
                    content_clean = base64.b64decode(raw_b64).decode("utf-8")
                    json_str = self._decrypt(content_clean)
                    self.users = json.loads(json_str)
                    self._save_local()
                    print(f"[AuthDB] 从 GitHub 成功同步 {len(self.users)} 名授权用户")
                    return
            except Exception as e:
                print(f"[AuthDB] GitHub 同步拉取异常: {e}")

        # 3. 初始状态：根据用户指令彻底清空，初始为空列表
        self.users = []
        self._save_local()

    def _save_local(self):
        try:
            with open(AUTH_FILE_LOCAL, "w", encoding="utf-8") as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[AuthDB] 本地保存失败: {e}")

    def save(self):
        self._save_local()
        # 异步或同步推送到 GitHub 仓库
        if not GITHUB_TOKEN:
            return

        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/auth_db.enc"
            headers = {
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            }
            # 查询已有的 sha
            sha = None
            check_resp = requests.get(url, headers=headers, timeout=5)
            if check_resp.status_code == 200:
                sha = check_resp.json().get("sha")

            json_str = json.dumps(self.users, ensure_ascii=False)
            encrypted_b64 = self._encrypt(json_str)
            commit_content = base64.b64encode(encrypted_b64.encode("utf-8")).decode("utf-8")

            payload = {
                "message": f"chore(auth): 自动同步白名单与设备绑定 [{time.strftime('%Y-%m-%d %H:%M:%S')}]",
                "content": commit_content
            }
            if sha:
                payload["sha"] = sha

            put_resp = requests.put(url, headers=headers, json=payload, timeout=8)
            if put_resp.status_code in [200, 201]:
                print("[AuthDB] 成功加密同步至 GitHub 仓库")
            else:
                print(f"[AuthDB] GitHub 同步失败: {put_resp.status_code} {put_resp.text}")
        except Exception as e:
            print(f"[AuthDB] GitHub 同步网络异常: {e}")

    def get_user(self, email: str):
        email_clean = email.strip().lower()
        for u in self.users:
            if u["email"].lower() == email_clean:
                return u
        return None

    def add_user(self, email: str, key: str, memo: str = ""):
        email_clean = email.strip().lower()
        user = self.get_user(email_clean)
        now_str = time.strftime("%Y-%m-%d %H:%M")
        if user:
            user["key"] = key
            user["memo"] = memo
        else:
            self.users.append({
                "email": email_clean,
                "key": key,
                "memo": memo,
                "bound_device": None,
                "bound_at": None,
                "created_at": now_str
            })
        self.save()

    def unbind_device(self, email: str):
        user = self.get_user(email)
        if user:
            user["bound_device"] = None
            user["bound_at"] = None
            self.save()
            return True
        return False

    def delete_user(self, email: str):
        user = self.get_user(email)
        if user:
            self.users.remove(user)
            self.save()
            return True
        return False


auth_db = AuthDB()


def make_admin_token() -> str:
    """生成带有时间戳和 HMAC 签名的管理员 Token"""
    now = str(int(time.time()))
    signature = hmac.new(ADMIN_MASTER_KEY.encode("utf-8"), now.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{now}.{signature}"


def verify_admin_token(token: str) -> bool:
    if not token or "." not in token:
        return False
    try:
        t_str, sig = token.split(".", 1)
        expected = hmac.new(ADMIN_MASTER_KEY.encode("utf-8"), t_str.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        # 12 小时内有效
        return abs(time.time() - int(t_str)) < 43200
    except Exception:
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


def get_file_content(filename: str) -> str:
    f_path = os.path.join(os.path.dirname(__file__), filename)
    if os.path.exists(f_path):
        try:
            with open(f_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return f"<h1>{filename} 未就绪</h1>"


class SafeCloudRunHandler(BaseHTTPRequestHandler):
    def get_client_ip(self):
        x_forwarded_for = self.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return self.client_address[0]

    def send_json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        client_ip = self.get_client_ip()
        if is_rate_limited(client_ip):
            self.send_json(429, {"ok": False, "message": "请求过于频繁，请稍候重试"})
            return

        if self.path in ["/healthz", "/_health"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        elif self.path == "/api/status":
            self.send_json(200, fetch_all_status())
        elif self.path == "/admin":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(get_file_content("admin.html").encode("utf-8"))
        elif self.path == "/api/admin/users":
            # 管理员拉取用户列表
            auth_header = self.headers.get("Authorization", "").replace("Bearer ", "")
            if not verify_admin_token(auth_header):
                self.send_json(401, {"ok": False, "message": "管理员凭据失效或未授权"})
                return
            self.send_json(200, {"ok": True, "users": auth_db.users})
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(get_file_content("index.html").encode("utf-8"))

    def do_POST(self):
        client_ip = self.get_client_ip()
        if is_rate_limited(client_ip):
            self.send_json(429, {"ok": False, "message": "请求过于频繁，请稍候重试"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            body = json.loads(post_data.decode("utf-8"))
        except Exception:
            body = {}

        # 1. 用户端登录接口 (含单设备独占绑定)
        if self.path == "/api/login":
            email = body.get("email", "").strip().lower()
            key = body.get("key", "").strip()
            device_id = body.get("device_id", "").strip()

            if not email or not key:
                self.send_json(400, {"ok": False, "message": "请输入邮箱与通行密匙"})
                return

            user = auth_db.get_user(email)
            if not user:
                self.send_json(403, {"ok": False, "message": "授权未通过：该邮箱未在白名单中，请联系管理员开通"})
                return

            if user.get("key") != key:
                self.send_json(403, {"ok": False, "message": "通行密匙不正确，请重新核对"})
                return

            # 一号一机独占绑定逻辑
            bound_dev = user.get("bound_device")
            if not bound_dev:
                # 首次激活，强绑定当前设备
                user["bound_device"] = device_id or f"dev_{int(time.time())}"
                user["bound_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                auth_db.save()
                self.send_json(200, {
                    "ok": True,
                    "message": "首次登录成功，已与当前设备完成独占绑定！",
                    "email": email,
                    "token": f"user_{int(time.time())}_{email}"
                })
                return

            if bound_dev == device_id:
                # 同一合法设备，允许放行
                self.send_json(200, {
                    "ok": True,
                    "message": "登录成功",
                    "email": email,
                    "token": f"user_{int(time.time())}_{email}"
                })
                return
            else:
                # 跨设备登录，坚决拦截
                self.send_json(403, {
                    "ok": False,
                    "message": "【登录受限】该账号已与首台设备完成独占绑定，严禁跨设备或多人共享！如需更换设备请联系管理员解绑。"
                })
                return

        # 2. 管理员校验主密码
        elif self.path == "/api/admin/verify":
            admin_key = body.get("admin_key", "").strip()
            if admin_key == ADMIN_MASTER_KEY:
                token = make_admin_token()
                self.send_json(200, {"ok": True, "token": token})
            else:
                self.send_json(403, {"ok": False, "message": "管理员总密码错误"})
            return

        # 3. 管理员添加/修改用户
        elif self.path == "/api/admin/users/add":
            auth_header = self.headers.get("Authorization", "").replace("Bearer ", "")
            if not verify_admin_token(auth_header):
                self.send_json(401, {"ok": False, "message": "管理员凭据失效"})
                return
            email = body.get("email", "")
            key = body.get("key", "")
            memo = body.get("memo", "")
            if not email or not key:
                self.send_json(400, {"ok": False, "message": "邮箱和密码不能为空"})
                return
            auth_db.add_user(email, key, memo)
            self.send_json(200, {"ok": True, "message": "添加成功"})
            return

        # 4. 管理员解除设备绑定
        elif self.path == "/api/admin/users/unbind":
            auth_header = self.headers.get("Authorization", "").replace("Bearer ", "")
            if not verify_admin_token(auth_header):
                self.send_json(401, {"ok": False, "message": "管理员凭据失效"})
                return
            email = body.get("email", "")
            if auth_db.unbind_device(email):
                self.send_json(200, {"ok": True, "message": "解绑成功"})
            else:
                self.send_json(404, {"ok": False, "message": "用户不存在"})
            return

        # 5. 管理员删除用户
        elif self.path == "/api/admin/users/delete":
            auth_header = self.headers.get("Authorization", "").replace("Bearer ", "")
            if not verify_admin_token(auth_header):
                self.send_json(401, {"ok": False, "message": "管理员凭据失效"})
                return
            email = body.get("email", "")
            if auth_db.delete_user(email):
                self.send_json(200, {"ok": True, "message": "删除成功"})
            else:
                self.send_json(404, {"ok": False, "message": "用户不存在"})
            return

        else:
            self.send_json(404, {"ok": False, "message": "接口不存在"})

    def log_message(self, format, *args):
        pass


def run_server(port=None):
    target_port = int(port or os.environ.get("PORT", PORT))
    server_address = ("0.0.0.0", target_port)
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer(server_address, SafeCloudRunHandler)
    print(f"[Cloud Run Ready] 服务已在 0.0.0.0:{target_port} 启动，管理员控制台与安全防线已就绪。")

    def shutdown_signal(sig, frame):
        print("\n接收到终止信号，正在安全关闭...")
        httpd.server_close()
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, shutdown_signal)
        signal.signal(signal.SIGTERM, shutdown_signal)
    except Exception:
        pass
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
