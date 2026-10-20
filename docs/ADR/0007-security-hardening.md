# ADR-0007：安全加固 —— SSRF 防护、命令白名单收敛、输出转义与运行一致性

- 状态：已采纳
- 日期：2026-10-20

## 背景

项目完成首版后，我用独立 AI 代码评审（DSH `dsh-code-review` 插件，子 Agent 审查当前 HEAD）对全仓库做了一次审查。评审报告指出了 2 个 P1 与多个 P2 问题，其中两个直接突破工具沙箱：

1. **`bash` 的 git 子命令白名单不严**：只限制了子命令名，未限制参数。`git diff --no-index <workspace 外文件>` 可读取任意文件、`git diff --output=<路径>` 可写任意文件，绕过文件工具的目录 jail。
2. **`fetch_url` 缺少 SSRF 防护**：只校验 `http(s)://` 前缀，模型可以请求 `127.0.0.1`、内网地址或云元数据服务（`169.254.169.254`），并把响应内容带回 LLM 上下文。

此外还有：推送发生在数据库写事务内（网络等待期间持有 SQLite 写锁）、轨迹落库异常被静默吞掉、强制收敛阶段模型没有 `publish_briefing` 工具导致必然失败、同一用户可并发触发多次运行、时区未统一、框架级 404/405 不走统一信封、邮件 HTML 未转义、`grep` 正则无回溯保护、`search_content` 对符号链接先读后校验等。

## 决策

| 问题 | 修复 |
|---|---|
| git 参数绕过 | 移除接触路径的 `diff`/`show`；剩余子命令改为 **token 级白名单**（`status --short` / `log --oneline -n N` / `rev-parse [--short] HEAD`），其余参数一律拒绝 |
| SSRF | 新增 `assert_public_url`：拒绝非 http(s)、localhost/*.local/*.internal、云元数据主机名；DNS 解析后逐个检查 IP（私网/回环/链路本地/保留/多播/未指定）；重定向**每一跳重新校验**，最多 3 跳 |
| 邮件 HTML 注入 | 所有 LLM/新闻源字段 `html.escape`，URL 仅允许 http(s) 否则降级为 `#` |
| 推送阻塞事务 | 简报与 run 状态先提交，推送移出事务；每渠道独立发送 + 短事务记录 `deliveries` |
| 轨迹异常被吞 | `emit()` 不再吞异常，持久化失败直接向上抛出 → run 标记 failed，状态一致 |
| 强制收敛无工具 | 收敛阶段只暴露 `publish_briefing` 的 schema，模型仍可提交简报 |
| 并发重复运行 | 进程内按用户加锁；已有运行中任务时复用/拒绝，不再双开 |
| 时区不一致 | `today` / `briefing_date` / 调度判定统一取 `APP_TIMEZONE`（ZoneInfo） |
| 404/405 信封 | 注册 `StarletteHTTPException` 处理器，统一 `{code,message,data}` |
| 邮箱并发 409 | 捕获 `IntegrityError` 映射为 409（而非 500） |
| grep 正则回溯 | 限制 pattern 长度、拒绝嵌套量词、跳过超长单行 |
| 符号链接先读后验 | `search_content` 先 `resolve()` 并校验前缀，再读取；越界直接跳过 |
| 进程重启遗留 running | 启动时把遗留 running 标记 failed，避免前端无限轮询/当天不再重试 |
| 上下文/成本失控 | 新增 `LLM_MAX_TOKENS`（单次回复上限）与 `AGENT_TOKEN_BUDGET`（累计 prompt 预算），超预算强制收尾 |

## 理由

- **沙箱是声明，必须可验证**：评审报告里的两条 P1 都能用一条命令复现，不修就等于沙箱失效；
- 这些修复都配套了回归测试（`tests/test_tools_bash.py`、`tests/test_news.py`、`tests/test_notify.py`、`tests/test_scheduler.py`），防止回退；
- 它也正好对应岗位要求「能指挥 AI，也能 review 并修正它的产出」——AI 写出的第一版并不天然正确，**审查 + 修复 + 回归测试**才是完整闭环。

## 代价

- `bash` 的 git 能力进一步收窄（仅仓库级只读信息），但 Agent 本就不需要更复杂的 git 操作；
- SSRF 校验增加一次 DNS 解析（每次抓取），对整体耗时影响可忽略；
- 推送移出事务后，极小概率出现"简报已落库、推送记录尚未写入"的中间态；用短事务逐条记账把窗口降到毫秒级，生产可进一步引入 outbox 模式。

## 未覆盖（诚实记录）

- DNS rebinding 窗口：`assert_public_url` 校验与 httpx 实际连接之间存在理论窗口，生产环境应配合出口代理 / 域名 allowlist；
- 进程内锁只在单实例有效，多实例部署需要分布式锁；
- 未做 token 级别流式输出与更细的预算裁剪策略。

## 补充：复审后由「真实运行」暴露的二次修复

安全加固上线后，用真实 DeepSeek 跑端到端验证，又暴露了三个问题（说明**只做单元测试不够，必须有真实链路回归**）：

| 问题 | 现象 | 修复 |
|---|---|---|
| Bing News RSS 带 `cc=CN` 参数 | 302 重定向到 Bing 首页（HTML），解析为空 → 模型反复换关键词把 24 步耗尽，运行 failed | 去掉 `cc` 参数；校验响应必须是 RSS/Atom；无结果时退化为「订阅源最新条目」兜底 |
| `LLM_MAX_TOKENS=1200` 太小 | 强制收敛阶段 `publish_briefing` 的 JSON 被截断，解析失败，一次本可成功的运行 failed | 默认提升到 4096；收敛阶段对「JSON 截断」再给一次重试机会（附带更严格的输出约束） |
| 无检索预算 | 模型可能调用十几次 `search_news`，成本与耗时不可控 | 系统提示加入「search_news 最多 5 次、够 5 条候选就收尾」；框架层再用 `AGENT_TOKEN_BUDGET=500000` 兜底 |

效果：修复前 13 轮 / 24 次工具调用 / 58s / 122K tokens；修复后 9 轮 / 15 次 / 33s / 72K tokens，且失败率明显下降。
