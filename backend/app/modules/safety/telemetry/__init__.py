"""特种设备遥测监控链（facilities-p2）。

子模块：
- store：快照幂等写入（唯一键 ON CONFLICT 防重放）；
- query：latest（每设备每指标最新值）与 history（按小时/日桶趋势序列）；
- rules：阈值规则引擎纯函数（票 02）；
- parser：模板/AI 解析分层（票 03）；
- source：TelemetrySourceAdapter 抽象与群消息实现（票 03）；
- collector：采集编排与 interval 任务（票 03）；
- notify：报警群卡与速递格子（票 02）。
"""
