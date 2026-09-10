"""Agent core 强化层（S2 统一工具执行管道）。

red-green-refactor 迁移：
- ``permissions.py``  自旧 ``business_agent/permissions.py`` 迁入（逻辑不变）
- ``pipeline.py``    ★ 统一工具执行管道（新写）

旧路径 ``business_agent.permissions`` 保留为 re-export shim，入口层 import 路径不变。
"""
