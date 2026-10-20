# Git 提交计划（工程规范）

## 约定

- **Conventional Commits**：`<type>(<scope>): <subject>`，中文正文说明「为什么」；
- 每个提交必须满足：`python -m pytest` 通过（或明确说明测试将在下一个提交补齐）；
- 一个提交只做一件事，避免「一锅端」；
- 提交顺序即开发顺序，可用 `git log --oneline` 直接复盘项目演进；
- 分支策略：`main` 保持可运行；功能开发可用短分支 + merge（本次单人 3 天项目，主干顺序提交即可）。

## 提交序列

| # | 提交信息 | 内容 | 对应阶段 |
|---|---|---|---|
| 1 | `chore: 初始化项目骨架与依赖清单` | `.gitignore`、`requirements*.txt`、`pyproject.toml`、`.env.example` | 脚手架 |
| 2 | `docs: 需求分析与 PRD` | `docs/PRD.md`、需求原文底稿 | 计划 |
| 3 | `docs: 架构设计与关键决策 ADR` | `docs/ARCHITECTURE.md`、`docs/ADR/*`、API 契约 | 计划 |
| 4 | `feat(config): 环境变量配置与数据层` | `app/config.py`、`app/db.py`、`app/models.py`、`migrations/001_init.sql` | 基础设施 |
| 5 | `feat(tools): 沙箱化文件与 bash 工具` | `app/tools/`（list_dir/read_file/search_content/write_file/bash） | 工具层 |
| 6 | `test(tools): 覆盖越权、超时与截断` | `tests/test_tools_*.py` | 工具层 |
| 7 | `feat(news): RSS/Bing 新闻检索与正文抽取` | `app/news/`、`app/tools/news_tools.py` | 能力层 |
| 8 | `feat(agent): function-calling ReAct 循环与轨迹` | `app/agent/`（llm/registry/loop/prompts/trace） | Agent 核心 |
| 9 | `test(agent): 假模型验证调用顺序非硬编码` | `tests/test_agent_loop.py` | Agent 核心 |
| 10 | `feat(briefing): 偏好过滤、去重与简报生成` | `app/services/`、`app/tools/publish_tool.py` | 业务 |
| 11 | `feat(api): FastAPI 接口与统一返回结构` | `app/api/`、`app/main.py`、`app/schemas.py` | 服务化 |
| 12 | `feat(ui): 单页前端（身份/偏好/历史/轨迹）` | `app/static/*` | 前端 |
| 13 | `feat(schedule): 每日定时任务` | `app/services/scheduler.py`、`app/cli.py` | 自动化 |
| 14 | `feat(notify): 站内/飞书/邮件可插拔推送` | `app/notify/*` | 推送 |
| 15 | `test(e2e): 离线端到端验收` | `tests/test_e2e_offline.py`、API 测试 | 验收 |
| 16 | `docs: README 与 5 分钟跑通指南` | `README.md` | 交付 |
| 17 | `chore(ci): GitHub Actions 校验` | `.github/workflows/ci.yml` | 交付 |
| 18 | `docs: 演示脚本与交付说明` | `docs/DEMO.md`、`docs/INTERVIEW_NOTES.md`、录屏 | 交付 |

## 提交信息示例

```
feat(agent): 实现由 LLM 决定工具顺序的 ReAct 循环

- 每轮把工具 JSON Schema + 用户偏好交给模型，tool_choice=auto
- 框架层仅做硬边界：max_steps、单工具超时、结果截断
- 新增 agent_runs / agent_steps 落库，供前端轨迹页复盘
```

## 反模式（明确避免）

- ❌ 一个 `init` 提交塞进全部代码；
- ❌ 提交信息写「update」「fix bug」；
- ❌ 把 `.env`、数据库文件、`__pycache__` 提交进仓库；
- ❌ 提交无法运行的中间状态（除明确的 WIP 分支）。
