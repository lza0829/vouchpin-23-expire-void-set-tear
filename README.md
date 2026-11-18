# Vouchpin（券钉簿）

骨架：券事件入湖 → 过期扫描 → 核销事实钉扎 → 批次互证。

**全局策略（唯一）：钉前必须扫描（expire-before-nail gate）**
- 钉扎请求须携带本次 `expire_scan_id`；无有效扫描、扫描跨日、扫描超 TTL（`PUT /api/settings/scan-ttl`，默认 3600s）、或扫描后有新发放，一律拒钉。
- 扫描覆盖该业务日发放未核集合，作废入事件流并落扫描批次（扫描时刻、发放数、作废笔数、覆盖事件点）。
- 钉批快照绑定 `expire_scan_id` 与扫描摘要（扫描时刻、作废笔数）；未扫描不得伪造 scan_id。
- 钉扎后当日发放/核销冻结。扫描服务、扫描批次、作废结果、钉闸、批快照、预览、总览同源（`expire_service.day_gate / seal_gate`）。

本地：
- API: `cd backend && python -m uvicorn app.main:app --port 10800`
- Web: `cd frontend && npm install && npm run dev`（5800）
- 测试: `cd backend && python -m pytest tests/`
