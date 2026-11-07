# -*- coding: utf-8 -*-
"""
微云充充电桩自动化状态轮询与监控系统 (正式实盘采集版)
模块：main.py
功能：全自动轮询常州大学科技园 4 台微云充设备，高可用容错采集并落盘到 CSV
"""

import os
import csv
import time
import random
import logging
from datetime import datetime
import requests
import urllib3

# 忽略本地代理或自签证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. 日志与基础配置
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ChargingMonitor")

# CSV 文件输出路径
CSV_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all_charging_trends.csv")
CSV_HEADER = ["Timestamp", "Device_Name", "Device_No", "Total_Slots", "Free_Slots", "Used_Slots"]

# 轮询时间间隔（900 秒 = 15 分钟）
POLL_INTERVAL_SECONDS = 900

# ==========================================
# 2. 目标设备列表（经实测校准：2号机真实编号为 L32022881）
# ==========================================
devices = [
    {"name": "1号机", "device_no": "L32022884"},
    {"name": "2号机", "device_no": "L32022881"},
    {"name": "3号机", "device_no": "L32022883"},
    {"name": "4号机", "device_no": "L32022882"}
]

# ==========================================
# 3. 真实抓包 API 接口与鉴权凭据 (实盘配置)
# ==========================================
API_URL = "https://saas.laichon.com/api/app/ebike/getDeviceInfo"

HEADERS = {
    "openid": "oOO3c4op_7fkh8C4-q0mFnbn-uIQ",
    "authorization": "bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczpcL1wvbW9iaWxlLmxhaWNob24uY29tIiwiaWF0IjoxNzkyNjY5NTUwLCJleHAiOjE3OTM5NjU1NTAsInN1YiI6MzI4ODk1NzEsInJvbGUiOiJ1c2VyIiwibW9uaXRvcl91c2VyX2lkIjoiN2YyZjM4YTViMzJkNzIwNGRhMzM4YzI0MzEyMDNmZjciLCJqdGkiOjk3MTg2MDI5NTU5NTg1NTg3MiwibmJmIjoxNzkyNjY5NTUwfQ==.Lnj6H-Lv4xt_QH4fDXgmwkPgYJM-P1TbBsQYRD8bPc8=",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541f0d) XWEB/25715",
    "xweb_xhr": "1",
    "service-code": "WYC-MI-WEIXIN",
    "content-type": "application/json",
    "accept": "*/*",
    "referer": "https://servicewechat.com/wxa68db1dabe823e7e/662/page-frame.html"
}

# ==========================================
# 4. 数据写入与解析核心逻辑
# ==========================================
def init_csv_file(file_path: str):
    """如果 CSV 文件不存在，初始化并写入标准表头"""
    if not os.path.exists(file_path):
        with open(file_path, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)
        logger.info(f"已创建新数据文件并写入表头: {file_path}")


def append_record_to_csv(file_path: str, record: list):
    """追加单条记录到 CSV 文件"""
    with open(file_path, mode="a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(record)


def parse_device_status(resp_json: dict) -> tuple:
    """
    根据微云充真实返回的 JSON 解析插孔状态
    返回元组: (total_slots, free_slots, used_slots)
    【经真机实测校准】：
      - gun_status == 0: 空闲可用插孔 (绿色边框白底)
      - gun_status == 1: 充电中/占用插孔 (绿底白字)
    """
    data = resp_json.get("data", {})
    guns = data.get("device_gunpoint", [])

    if not guns:
        logger.warning("未在该设备响应中解析到插孔列表 (device_gunpoint 为空)")
        return 0, 0, 0

    total_slots = len(guns)
    # gun_status 为 0 代表空闲可用
    free_slots = sum(1 for g in guns if g.get("gun_status") == 0)
    used_slots = total_slots - free_slots

    return total_slots, free_slots, used_slots


def fetch_device_data(session: requests.Session, device: dict) -> list:
    """
    发送 POST 请求抓取单台设备最新状态
    数据格式: [Timestamp, Device_Name, Device_No, Total_Slots, Free_Slots, Used_Slots]
    """
    device_name = device["name"]
    device_no = device["device_no"]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {"device_no": device_no}

    response = session.post(
        API_URL,
        headers=HEADERS,
        json=payload,
        timeout=10,
        verify=False
    )
    response.raise_for_status()
    resp_json = response.json()

    if resp_json.get("code") != 0:
        msg = resp_json.get("msg", "未知错误")
        logger.warning(f"[{device_name} - {device_no}] 接口返回业务错误提示: {msg}")

    total_slots, free_slots, used_slots = parse_device_status(resp_json)
    logger.info(
        f"[{device_name} - {device_no}] 抓取成功 -> "
        f"总孔数: {total_slots}, 空闲: {free_slots}, 占用: {used_slots}"
    )

    return [now_str, device_name, device_no, total_slots, free_slots, used_slots]


# ==========================================
# 5. 主轮询死循环引擎
# ==========================================
def main_poll_loop():
    """主轮询逻辑：每 15 分钟遍历抓取 4 台设备，每台间隔 2~5 秒防封，全量容错"""
    logger.info("=" * 60)
    logger.info("微云充自动化充电桩监控系统 (常州大学西太湖校区)")
    logger.info("开发者: 日月潭 | 监控设备: 4 台 | 轮询周期: 15分钟")
    logger.info(f"数据落盘路径: {CSV_FILE_PATH}")
    logger.info("=" * 60)

    # 初始化本地 CSV 存储文件
    init_csv_file(CSV_FILE_PATH)

    session = requests.Session()
    session.trust_env = False  # 直连公网，不受本地代理影响
    round_count = 1

    while True:
        round_start_time = time.time()
        round_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"\n>>> 开始第 {round_count} 轮数据轮询 [{round_time_str}] <<<")

        # 遍历设备列表
        for idx, dev in enumerate(devices, start=1):
            dev_name = dev["name"]
            dev_no = dev["device_no"]

            try:
                record = fetch_device_data(session, dev)
                # 只有成功解析到孔位数据才写入，防止脏数据
                if record[3] > 0:
                    append_record_to_csv(CSV_FILE_PATH, record)
            except requests.exceptions.Timeout:
                logger.error(f"[{dev_name} - {dev_no}] 请求超时 (timeout=10s)，跳过本次采集。")
            except requests.exceptions.RequestException as e:
                logger.error(f"[{dev_name} - {dev_no}] 网络请求异常: {e}，跳过本次采集。")
            except Exception as e:
                logger.error(f"[{dev_name} - {dev_no}] 数据处理异常: {e}，跳过本次采集。")

            # 防封抖动策略：每请求完一台设备，强制休眠 2.0 ~ 5.0 秒
            if idx < len(devices):
                delay = round(random.uniform(2.0, 5.0), 2)
                logger.debug(f"防封休眠: 等待 {delay} 秒后请求下一台设备...")
                time.sleep(delay)

        logger.info(f">>> 第 {round_count} 轮轮询完成，数据已成功追加落盘。")

        # 距离下一轮还有多久
        elapsed = time.time() - round_start_time
        sleep_time = max(0.0, POLL_INTERVAL_SECONDS - elapsed)
        next_poll_time = datetime.fromtimestamp(time.time() + sleep_time).strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"休眠等待中，预计下次采集时间: {next_poll_time} (休眠 {int(sleep_time)} 秒)\n")

        round_count += 1
        time.sleep(sleep_time)


if __name__ == "__main__":
    try:
        main_poll_loop()
    except KeyboardInterrupt:
        logger.info("接收到用户终止指令 (Ctrl+C)，监控轮询已安全退出。")
