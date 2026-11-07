# -*- coding: utf-8 -*-
"""
充电桩数据分析与 24 小时用电高峰可视化脚本
模块：analysis.py
功能：处理 all_charging_trends.csv，生成多设备 24 小时占用率折线图及周级高峰热力图
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import seaborn as sns

# ==========================================
# 1. 中文字体自适应配置（防止乱码）
# ==========================================
def configure_matplotlib_fonts():
    """根据操作系统自动配置 Matplotlib 中文字体与符号显示"""
    font_candidates = [
        "Microsoft YaHei",   # Windows 微软雅黑
        "SimHei",            # Windows 黑体
        "PingFang SC",       # macOS 苹方
        "Hiragino Sans GB",  # macOS 冬青黑体
        "WenQuanYi Micro Hei", # Linux 文泉驿
        "DejaVu Sans"
    ]
    plt.rcParams["font.sans-serif"] = font_candidates
    plt.rcParams["axes.unicode_minus"] = False  # 正常显示负号
    plt.rcParams["font.size"] = 11

configure_matplotlib_fonts()

# 基础路径
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE_PATH = os.path.join(CURRENT_DIR, "all_charging_trends.csv")
CHART_LINE_PATH = os.path.join(CURRENT_DIR, "charging_occupancy_24h.png")
CHART_HEATMAP_PATH = os.path.join(CURRENT_DIR, "charging_weekly_heatmap.png")


# ==========================================
# 2. 模拟数据生成器（在刚部署无历史数据时供体验）
# ==========================================
def generate_mock_trends_csv(file_path: str, days: int = 14):
    """
    生成过去两周（14天）逼真的充电桩轮询模拟数据，写入 CSV。
    模拟现实规律：夜间 18:00~23:00 为用电高峰，白天工作时间较低，周末整体偏高。
    """
    print(f"[提示] 正在生成过去 {days} 天的模拟测试数据至: {file_path}")
    devices = [
        {"name": "1号机", "device_no": "L32022884", "bias": 0.05},
        {"name": "2号机", "device_no": "L37022881", "bias": -0.05},
        {"name": "3号机", "device_no": "L32022883", "bias": 0.10},
        {"name": "4号机", "device_no": "L32022882", "bias": -0.10}
    ]

    records = []
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)

    curr = start_time
    total_slots = 10

    while curr <= end_time:
        hour = curr.hour
        weekday = curr.weekday()  # 0=周一, 6=周日

        # 基础用电高峰曲线（晚高峰 18-23 点最高，早高峰 7-9 点次高，凌晨逐渐充满）
        if 0 <= hour < 6:
            base_occupancy = 0.80  # 凌晨通宵充电占满
        elif 6 <= hour < 10:
            base_occupancy = 0.50  # 早间车主陆续拔枪骑车出门
        elif 10 <= hour < 17:
            base_occupancy = 0.35  # 工作时间小区充电少
        elif 17 <= hour < 22:
            base_occupancy = 0.88  # 下班集中归家充电高峰
        else:
            base_occupancy = 0.85

        # 周末整体用电率略高
        if weekday in [5, 6]:
            base_occupancy = min(0.95, base_occupancy + 0.08)

        now_str = curr.strftime("%Y-%m-%d %H:%M:%S")

        for dev in devices:
            rate = np.clip(base_occupancy + dev["bias"] + np.random.normal(0, 0.08), 0.1, 1.0)
            used = int(round(total_slots * rate))
            free = total_slots - used
            records.append({
                "Timestamp": now_str,
                "Device_Name": dev["name"],
                "Device_No": dev["device_no"],
                "Total_Slots": total_slots,
                "Free_Slots": free,
                "Used_Slots": used
            })

        curr += timedelta(minutes=15)

    df_mock = pd.DataFrame(records)
    df_mock.to_csv(file_path, index=False, encoding="utf-8-sig")
    print(f"[提示] 模拟数据生成完毕，共 {len(df_mock)} 条记录。")


# ==========================================
# 3. 数据清洗与特征提取
# ==========================================
def load_and_clean_data(file_path: str) -> pd.DataFrame:
    """读取 CSV 并清洗提取时间维度与占用率指标"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"未找到数据文件: {file_path}")

    df = pd.read_csv(file_path, encoding="utf-8-sig")
    if df.empty or len(df) < 4:
        raise ValueError("数据文件记录过少，不足以进行统计分析。")

    # 1. 转换为 datetime
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])

    # 2. 提取特征
    df["Hour"] = df["Timestamp"].dt.hour
    df["DayOfWeek_Num"] = df["Timestamp"].dt.dayofweek  # 0: 周一, 6: 周日
    
    # 中文星期映射
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    df["DayOfWeek"] = df["DayOfWeek_Num"].apply(lambda x: weekday_names[x])

    # 3. 计算占用率（防除零保护）
    df["Total_Slots"] = pd.to_numeric(df["Total_Slots"], errors="coerce").fillna(10)
    df["Used_Slots"] = pd.to_numeric(df["Used_Slots"], errors="coerce").fillna(0)
    df["Occupancy_Rate"] = df["Used_Slots"] / df["Total_Slots"].replace(0, 1)

    return df


# ==========================================
# 4. 图表 1：多设备 24 小时占用率折线对比图
# ==========================================
def plot_device_hourly_comparison(df: pd.DataFrame, output_path: str):
    """在一张图中绘制 4 台设备在一天 24 小时中的平均插孔占用率对比折线"""
    # 按 设备名称 和 小时 聚合计算平均占用率
    grouped = df.groupby(["Hour", "Device_Name"])["Occupancy_Rate"].mean().unstack()

    plt.figure(figsize=(12, 6), dpi=150)
    
    # 颜色与标记配置
    styles = {
        "1号机": {"color": "#1f77b4", "marker": "o"},
        "2号机": {"color": "#2ca02c", "marker": "s"},
        "3号机": {"color": "#ff7f0e", "marker": "^"},
        "4号机": {"color": "#d62728", "marker": "d"}
    }

    hours = np.arange(24)

    for dev_name in sorted(grouped.columns):
        series = grouped[dev_name].reindex(hours)
        style = styles.get(dev_name, {"color": None, "marker": "o"})
        plt.plot(
            hours,
            series.values * 100,
            label=dev_name,
            linewidth=2.2,
            marker=style["marker"],
            markersize=6,
            color=style["color"],
            alpha=0.9
        )

    plt.title("常州大学西太湖校区 · 各充电桩 24 小时平均占用率对比", fontsize=15, pad=15, fontweight="bold")
    plt.xlabel("时间 (小时 00:00 - 23:00)", fontsize=12, labelpad=10)
    plt.ylabel("插孔平均占用率 (%)", fontsize=12, labelpad=10)

    plt.xticks(hours, [f"{h:02d}:00" for h in hours], rotation=45)
    plt.yticks(np.arange(0, 101, 10))
    plt.gca().yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100))
    plt.ylim(-2, 105)

    # 参考辅助线：80% 警戒高峰线
    plt.axhline(y=80, color="gray", linestyle="--", linewidth=1.2, alpha=0.7, label="高负荷警戒线 (80%)")

    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(title="设备名称 (开发者: 日月潭)", loc="lower right", frameon=True, shadow=True)
    plt.tight_layout()

    plt.savefig(output_path, dpi=200)
    print(f"[OK] 图表 1 已保存至: {output_path}")
    plt.close()


# ==========================================
# 5. 图表 2：周级总体充电热度热力图 (Heatmap)
# ==========================================
def plot_weekly_hourly_heatmap(df: pd.DataFrame, output_path: str):
    """合并 4 台设备，绘制以星期为纵轴、小时为横轴的充电高峰热力图"""
    weekday_order = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    # 交叉透视表：纵轴 Weekday，横轴 Hour，值为整体平均占用率
    pivot_table = df.pivot_table(
        index="DayOfWeek",
        columns="Hour",
        values="Occupancy_Rate",
        aggfunc="mean"
    ).reindex(weekday_order)

    # 补齐 0-23 小时列
    for h in range(24):
        if h not in pivot_table.columns:
            pivot_table[h] = np.nan
    pivot_table = pivot_table.sort_index(axis=1)

    plt.figure(figsize=(14, 6), dpi=150)
    
    # 绘制热力图，百分比数值标注
    ax = sns.heatmap(
        pivot_table * 100,
        cmap="YlOrRd",  # 从黄到橙到红，直观展示低负荷至极高负荷
        annot=True,
        fmt=".0f",
        cbar_kws={"label": "整体占用率 (%)", "format": "%.0f%%"},
        linewidths=0.5,
        linecolor="#f0f0f0"
    )

    plt.title("常州大学西太湖校区 · 充电桩总体负荷热力图 (开发者: 日月潭)", fontsize=15, pad=15, fontweight="bold")
    plt.xlabel("一天中的时间 (小时 00:00 - 23:00)", fontsize=12, labelpad=10)
    plt.ylabel("星期", fontsize=12, labelpad=10)

    # 格式化 X 轴标签
    ax.set_xticklabels([f"{h}点" for h in range(24)], rotation=0)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    print(f"[OK] 图表 2 已保存至: {output_path}")
    plt.close()


# ==========================================
# 6. 主程序入口
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="充电桩数据清洗与高峰可视化分析")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="强制生成模拟两周历史数据以供测试出图"
    )
    args = parser.parse_args()

    # 如果指定了 --mock，或者当前没有 csv 文件，自动生成演示数据
    if args.mock or not os.path.exists(CSV_FILE_PATH):
        generate_mock_trends_csv(CSV_FILE_PATH, days=14)

    print(f"\n>>> 开始读取并分析数据: {CSV_FILE_PATH}")
    df = load_and_clean_data(CSV_FILE_PATH)
    print(f"数据总行数: {len(df)} 行，时间跨度: {df['Timestamp'].min()} ~ {df['Timestamp'].max()}")

    # 生成图表 1
    plot_device_hourly_comparison(df, CHART_LINE_PATH)

    # 生成图表 2
    plot_weekly_hourly_heatmap(df, CHART_HEATMAP_PATH)

    print("\n可视化分析已圆满完成！已输出：")
    print(f"1. {CHART_LINE_PATH}")
    print(f"2. {CHART_HEATMAP_PATH}")


if __name__ == "__main__":
    main()
