# 微云充智能监控系统 (常州大学西太湖校区)

常州大学西太湖校区微云充充电桩实时状态智能监控系统。

- **开发者**：日月潭
- **支持端**：手机 PWA、Android APK、Web 看板、本地轮询
- **云端部署**：支持 Docker / Render / Google Cloud Run 容器化一键部署

## 项目结构
- `app_cloud_run.py`: 生产级云原生 Web 服务（多线程并发、IP 限流防刷、6秒缓存保护）
- `Dockerfile`: 轻量级容器构建规范
- `requirements.txt`: 依赖清单
- `main.py`: 后台数据轮询采集引擎
- `query_now.py`: 终端即时查孔工具
- `analysis.py`: 历史数据分析与高峰热力图生成工具
