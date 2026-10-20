-- 002_add_evidence_level.sql —— 为每条简报条目补充「证据分级」
-- 取值：已读取原网页正文片段 / 仅来源摘要，未读正文 / 仅标题，信息有限
-- 说明：SQLite 的 ALTER TABLE ADD COLUMN 支持 NOT NULL + DEFAULT，历史数据自动填充空串。

ALTER TABLE briefing_items ADD COLUMN evidence_level VARCHAR(40) NOT NULL DEFAULT '';
