# Vouchpin（券钉簿）

骨架：券事件入湖 → 过期扫描 → 核销事实钉扎 → 批次互证。

**全局策略（唯一）：钉前必须扫描（expire-before-nail gate）**
- 钉扎请求须携带本次 `expire_scan_id`；无有效扫描、扫描跨日、扫描超 TTL（`PUT /api/settings/scan-ttl`，默认 3600s）、或扫描后有新发放，一律拒钉。
- 扫描覆盖该业务日发放未核集合，作废入事件流并落扫描批次（扫描时刻、发放数、作废笔数、覆盖事件点）。
- 钉批快照绑定 `expire_scan_id` 与扫描摘要（扫描时刻、作废笔数）；未扫描不得伪造 scan_id。
- 钉扎后当日发放/核销冻结。扫描服务、扫描批次、作废结果、钉闸、批快照、预览、总览同源（`expire_service.day_gate / seal_gate`）。

**作废口径（唯一）：扫描清单为准，事实 void 态为落定记录**
- 扫描清单（`expire_scan_items`）宣告的每个券码都必须落成 `redeem_facts.status='void'`；从未核销的过期券也补建 0 额 void 事实，使「清单 / 事实 void 态 / 总览过期计数」逐条对齐。
- 扫描整批原子提交：中途失败、故障注入或写锁被占一律整批回滚，绝不留半截 void。
- 已 void 的券码不得进入预览 / sealed 明细；已 sealed 的券码被作废旁路或手工 void 时自动出明细，批头笔数/合计同步收敛（批头不含作废额）。
- 「扫描清单已宣告、事实未 void」的撕裂态：预览/钉扎一律拒绝并要求重扫；重扫按事件流 void 重新对齐事实。
- 扫描与钉扎交错时写锁等待，超时即 409（`SQLITE_LOCK_TIMEOUT`，默认 5s），不消费旧清单。


本地：
- API: `cd backend && python -m uvicorn app.main:app --port 10800`
- Web: `cd frontend && npm install && npm run dev`（5800）
- 测试: `cd backend && python -m pytest tests/`
