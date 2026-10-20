# ADR-0003：SQLite + 纯 SQL migration，而不是 MySQL + Alembic

- 状态：已采纳
- 日期：2026-10-20

## 背景

题目约束要求「提供建表 SQL 或 migration 脚本」。选项 B 明确要求 MySQL/Redis，但选项 A 没有；A 的交付重心在 Agent Loop 与 5 分钟可运行性。

## 决策

- 默认使用 **SQLite**（单文件，零安装），通过 SQLAlchemy 的 `DATABASE_URL` 保留切换 MySQL/Postgres 的能力；
- 表结构用 **纯 SQL migration**（`migrations/001_init.sql`）+ 一个 40 行的执行器（`schema_migrations` 记账），不引入 Alembic。

## 理由

1. 评审「5 分钟跑通」：SQLite 不需要额外装数据库、配账号；
2. 题目只要求"提供建表 SQL 或 migration 脚本"，纯 SQL 文件比 Alembic 更能直接阅读与审查；
3. 表结构规模（7 张表）尚不值得引入迁移框架；执行器足够幂等。

## 代价

- 复杂 schema 演进（改列、回滚）能力弱于 Alembic；如未来需要，可在保持 `migrations/*.sql` 前提下平滑迁移到 Alembic；
- SQLite 并发写有限，但本项目是单机演示、低并发场景。

## 备选方案

| 方案 | 放弃原因 |
|---|---|
| MySQL + Alembic | 更接近真实生产，但评审要多装一个数据库服务，违背 5 分钟目标 |
| SQLModel / ORM auto-create | 无法体现"建表 SQL/migration"交付物，且不可审计 |
