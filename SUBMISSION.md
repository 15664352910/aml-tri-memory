# 参赛材料清单（Textual Memory · Open-source Methods）

> 状态对照用。比赛规则：<https://agentmemoryleaderboard.ai/rules>；API 契约：<https://agentmemoryleaderboard.ai/api-guide>。材料截止 2026-10-31 23:59 (UTC+8)。

## 1. 身份与版本

- [ ] 系统名称：AML Tri-Memory；版本号（评测冻结版，如 `1.0-eval`）
- [ ] 联系人姓名 / 邮箱 / 单位或团队名
- [ ] 赛道与组别声明：Textual Memory / Open-source Methods

## 2. API 与部署

- [ ] 线上 Add endpoint：`https://<host>/aml/add`
- [ ] 线上 Search endpoint：`https://<host>/aml/search`
- [ ] 认证方式：`Authorization: Bearer <Memory System Key>`（key 经安全渠道单独提交，不入库、不进截图/邮件）
- [ ] 容量声明：并发上限、Add/Search 超时预算、rate limit（待压测后填实测值）
- [ ] 版本一致性：线上部署 commit hash 与提交材料所列一致
- [ ] `/health` 监控与进程守护方案说明

## 3. 开源与归属

- [ ] 公开 GitHub 仓库链接 + 固定 commit
- [ ] LICENSE（建议 MIT/Apache-2.0）
- [ ] 归属声明：方法源于 Tri-Memory 研究原型（人格/事件/世界三层记忆 + 类型化治理），本仓库为面向 AML 契约的独立重实现
- [ ] 外部依赖清单与各自许可证（FastAPI/pydantic/uvicorn/psycopg，见 requirements.txt）
- [ ] 方法变更说明：相对研究原型的改动（契约包装、user_id 隔离、同步幂等摄入、确定性检索打分、abstention 空数组）
- [ ] **前置（一票否决）：专利申请状态确认完成后再公开仓库**

## 4. 方法与公开信息

- [ ] 方法描述（可用 README 方法节 + governance 要点）
- [ ] 允许公开展示的信息清单：团队名、系统名、版本、分数、方法名
- [ ] Submission notes 完整版

## 5. 流程节点

- [ ] 提交参赛请求（含上述材料）
- [ ] 平台审查线上 API 与材料 → 获得 Eval Key
- [ ] Smoke：Add/Search/认证/端到端验证通过
- [ ] Full：正式评测完成，结果无缺漏无重复
- [ ] 版本一致性核查 → 审核 → 榜单发布（2026 年 11 月中旬）

## 6. 数据合规

- [ ] 评测数据仅用于评测，不训练、不分析、不外传
- [ ] 服务无请求日志；评测结束后 30 天内清除存储数据（runbook：删除 `memory_records` / `idempotent_responses` 两表或整实例）
