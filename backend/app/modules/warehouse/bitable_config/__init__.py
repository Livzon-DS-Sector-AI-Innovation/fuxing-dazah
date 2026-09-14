"""仓库模块 Bitable 连接配置（bitable_config）。

- registry：从 bitable_schema.TABLES 单向导出 10 张表的连接默认值（唯一事实源，
  禁止手抄坐标）；
- store：随票 05 落地（回退链 DB 活行 → env 按 base_key → 代码快照）。
"""
