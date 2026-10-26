"""厂区风险分区图卡底座（3.x 平台关联 F2）。

三个子模块：
- asset：平台风险分区 payload → 归一化资产（docs 权威存档 + frontend 打包副本）。
- mapping：地点文本 → 分区 id 的确认映射匹配（pins 端点消费）。
- pins：当日作业票/报警按分区聚合（pins 端点消费）。

坐标口径（2026-10-26 真机探针）：rail.pointDTOS 为经纬度（x=经度 y=纬度，
福清厂区 ~119.28E/25.46N），pointsList 为本地米制平面坐标嵌套 JSON 字符串，
两者点数一一对应；资产主坐标取 pointDTOS（朝向天然北上，不依赖平台 jsmap
底图配置），米制串仅作回退源。riskLevel 1=低风险/2=一般风险，14 分区未填。
"""
