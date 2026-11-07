# -*- coding: utf-8 -*-
"""
微云充实时插孔状态即时查询工具
模块：query_now.py
功能：实时请求 4 台设备，秒级输出当前各插孔空闲与占用详情（含具体空闲孔号推荐）
"""

import sys
import time
import requests
import urllib3

# 兼容 Windows GBK 控制台，防止 Emoji 或特殊符号引发 UnicodeEncodeError
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 忽略本地自签证书或代理告警
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# API 接口与鉴权凭据
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


def query_current_status():
    """即时查询并打印所有设备插孔状态看板"""
    query_time_str = time.strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "=" * 62)
    print("      常州大学西太湖校区 · 微云充实时插孔看板")
    print(f"        查询时间: {query_time_str} | 开发者: 日月潭")
    print("=" * 62)

    session = requests.Session()
    session.trust_env = False  # 直连公网，不受代理环境干扰

    total_slots_all = 0
    free_slots_all = 0
    used_slots_all = 0

    for dev in devices:
        dev_name = dev["name"]
        dev_no = dev["device_no"]
        payload = {"device_no": dev_no}

        try:
            resp = session.post(API_URL, headers=HEADERS, json=payload, timeout=8, verify=False)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            guns = data.get("device_gunpoint", [])

            if not guns:
                print(f"[{dev_name} - {dev_no}] [X] 接口未返回插孔列表")
                continue

            total = len(guns)
            # gun_status == 0 为空闲可用插孔，其余为占用/充电中
            free_guns = [g.get("gun_no") for g in guns if g.get("gun_status") == 0]
            used_count = total - len(free_guns)
            free_count = len(free_guns)

            total_slots_all += total
            free_slots_all += free_count
            used_slots_all += used_count

            # 格式化输出
            if free_count > 0:
                free_slots_str = ", ".join([f"{num}号孔" for num in free_guns])
                print(f"[{dev_name} - {dev_no}] [有空位]  空闲: {free_count:2d}  /  占用: {used_count:2d}")
                print(f"     >> 推荐空闲插孔: [ {free_slots_str} ]")
            else:
                print(f"[{dev_name} - {dev_no}] [已占满]  空闲:  0  /  占用: {total:2d}")

        except Exception as e:
            print(f"[{dev_name} - {dev_no}] [警告] 查询失败: {e}")

    print("-" * 62)
    if total_slots_all > 0:
        occupancy_rate = (used_slots_all / total_slots_all) * 100
        print(f"全区汇总: 总插孔 {total_slots_all} 个 | 当前空闲 {free_slots_all} 个 | 总体占用率 {occupancy_rate:.1f}%")
        if free_slots_all == 0:
            print("提示: 当前所有车位已全部占满，建议稍后通过本脚本刷新捡漏。")
        else:
            print(f"提示: 发现 {free_slots_all} 个空闲插孔，建议带上充电器尽快前往！")
    print("=" * 62 + "\n")


if __name__ == "__main__":
    query_current_status()
