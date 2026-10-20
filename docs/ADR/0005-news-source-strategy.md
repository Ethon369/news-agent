# ADR-0005：新闻源用 RSS + Bing News RSS，免 API Key 为主，Tavily 作为可选增强

- 状态：已采纳
- 日期：2026-10-20

## 背景

题目说「新闻从哪来（包括让模型自己去搜索）由你自己决定」。可选方案：商业搜索 API（Tavily/Serper/Bocha）、RSS、直接爬新闻站、让模型自带联网。

## 决策

1. **默认零密钥**：Bing News RSS 搜索（`https://www.bing.com/news/search?q=…&format=rss`）+ 一组固定 RSS 源（Hacker News、arXiv cs.AI、TechCrunch AI、机器之心等）；
2. 由 `search_news(query, days, limit)` 工具统一封装，按偏好话题/关键词分别检索后合并去重；
3. 正文用 `fetch_url` 抓取并抽取可读文本（去脚本/样式/导航）；
4. Tavily 等商业搜索只作为**可选 provider**，不配置也能完整运行。

## 理由

1. 评审 5 分钟跑通不能依赖申请 Key；
2. RSS 是新闻站官方提供的结构化出口，稳定、合规、成本低；
3. Bing News RSS 实际上就是"模型发起搜索"的落地方式：模型自己决定 query 与次数。

## 代价

- RSS 的时效性与覆盖面不如商业搜索 API；
- 个别源可能反爬/限流（已做单源失败降级）。

## 备选方案

| 方案 | 放弃原因 |
|---|---|
| 只用 Tavily | 需 Key，评审成本高 |
| 直接爬 Google News | 反爬/封 IP 风险高 |
| 模型自带联网（provider 内置搜索） | 依赖特定厂商，可移植性差 |
