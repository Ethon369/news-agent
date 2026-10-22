# ADR-0008：链接溯源 + 证据分级（吸收自对比实现）

- 状态：已采纳
- 日期：2026-10-20

## 背景

在完成首版交付后，我对比评审了另一个同类实现（`daily-ai-news-agent`，同样实现选项 A）。它有一个比我们更强的设计：

> 模型**不能输出 URL**，只能引用「本次运行已采集新闻的编号（source_ids）」，程序再根据编号附加真实链接。

这从结构上杜绝了「模型编造链接」。我们的 `publish_briefing` 之前只校验 URL 是否以 `http(s)` 开头——模型理论上可以编一个看似合理、实际不存在的链接，或把旧新闻的链接安到新标题上。这是真实缺口。

同时，它的「证据分级」（已读正文 / 仅来源摘要 / 仅标题）能让读者判断摘要可信度，也是我们缺的。

## 决策

### 1. 链接溯源（URL provenance）

- `search_news` 把返回的每条链接归一化后登记到 `ToolContext.committed_urls`；
- `fetch_url` 把「请求 URL + 重定向后的最终 URL」都登记，并标记 `fetched_urls`；
- `publish_briefing` 校验每个 `items[].url` 归一化后必须属于已登记集合，否则返回结构化错误（`invalid_briefing`）并回喂模型，要求它只使用工具返回过的链接；
- 本次运行**没有任何采集**时直接拒绝发布（`no_news_collected`），避免模型凭空生成简报；
- 归一化复用 `normalize_url`（去 utm/fragment/www/尾斜杠），避免「同一链接带跟踪参数」被误杀。

### 2. 证据分级（evidence level）

发布时为每条新闻计算并落库：

| 取值 | 判定条件 |
|---|---|
| `已读取原网页正文片段` | 该 URL 在本次运行中 `fetch_url` 成功提取正文 |
| `仅来源摘要，未读正文` | 有摘要但没读正文 |
| `仅标题，信息有限` | 既无正文也无摘要 |

- 新增 migration `002_add_evidence_level.sql`（`briefing_items.evidence_level`，旧数据默认空串，幂等）；
- Markdown 简报与前端详情均展示「证据范围」。

### 3. Bing apiclick 解包

Bing News RSS 部分条目给的是 `bing.com/news/apiclick.aspx?url=<编码后的真实链接>`。若不处理：

- 去重会按跳转链接判重（同一文章不同跳转参数导致重复）；
- 溯源集合里存的是跳转链接，而模型/抓取侧拿到的是真实链接，容易被误判为「未采集」。

因此在 `_parse_feed` 里对 bing 来源解包 `url` 参数，直接使用真实目标链接。

## 为什么这样做

- **链接是新闻简报里最硬的可验证事实**。摘要可以写得差，但链接不能假；把「链接只能来自工具结果」变成程序断言，比在提示词里写「不要编造」可靠得多；
- 证据分级直接回答评审的疑问：「这条摘要到底基于正文还是只有标题？」；
- 这两点都能用离线单测覆盖，不依赖真实模型（`tests/test_publish_trace.py`）。

## 代价

- 真实运行中，如果模型引用了链接的变体（如改了协议、加了未被归一化规则覆盖的参数），会被拒绝并多花一轮修正；已在提示词与工具描述中明确「必须使用 search_news / fetch_url 返回过的链接」；
- 溯源只保证「链接真实存在于本次采集」，**不保证摘要与链接语义对应**（模型仍可能张冠李戴）——这需要双源核实/人工复核，已在 README 的已知限制中说明；
- 新增一列 schema，旧库需要执行 migration（启动时自动应用）。

## 测试

- `test_url_must_come_from_collected_set`：编造 URL 被拒；
- `test_url_normalization_allows_tracking_variants`：带 utm 的同一链接不被误杀；
- `test_evidence_levels` / `test_title_only_evidence`：三级证据判定；
- `test_publish_handler_requires_collected_news`：未采集不能发布；
- `test_parse_feed_unwraps_bing_apiclick_links`：跳转链接解包；
- API/E2E 断言：证据分级已落库并出现在简报 Markdown 中。
