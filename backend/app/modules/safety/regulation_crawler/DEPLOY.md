# changedetection.io 部署与集成指南

## 概述

changedetection.io 作为外部变更监控组件，定时检测政府法规页面的内容变化，
检测到变更时通过 Webhook 通知 dazah 的法规抓取系统。

## 部署 changedetection.io

### Docker 部署（推荐）

```bash
docker run -d \
  --name changedetection \
  -p 5000:5000 \
  -v changedetection-data:/datastore \
  ghcr.io/dgtlmoon/changedetection.io:latest
```

或使用 docker-compose：

```yaml
version: '3'
services:
  changedetection:
    image: ghcr.io/dgtlmoon/changedetection.io:latest
    container_name: changedetection
    ports:
      - "5000:5000"
    volumes:
      - changedetection-data:/datastore
    restart: unless-stopped

volumes:
  changedetection-data:
```

Web UI 访问：`http://<host>:5000`

### pip 安装

```bash
pip install changedetection.io
changedetection.io --port 5000
```

## 配置监控规则

### 1. 添加监控 URL

在 changedetection.io Web UI 中添加以下 URL：

| 监控 URL | 说明 | 检测频率 |
|----------|------|---------|
| https://www.mem.gov.cn/fw/flgb/ | 应急管理部法规公告 | 每日 |
| https://www.gov.cn/zhengce/zhengcewenjianku/ | 中国政府网政策文件库 | 每日 |
| https://flk.npc.gov.cn | 国家法律法规数据库 | 每日 |
| https://openstd.samr.gov.cn/bzgk/gb/std_list | 国家标准全文公开 | 每周 |

### 2. 配置 Webhook 通知

每个 Watch 的 Notifications 设置：

**Notification URL**：
```
http://<dazah-host>:8000/api/v1/safety/regulation-crawler/webhook/changedetection
```

**Notification Body (JSON)**：
```json
{
  "watch_url": "{{watch_url}}",
  "watch_title": "{{watch_title}}",
  "current_snapshot": "{{current_snapshot}}",
  "diff": "{{diff}}",
  "previous_md5": "{{previous_md5}}",
  "current_md5": "{{current_md5}}",
  "viewed": "{{viewed}}",
  "source_tag": "{{tags}}"
}
```

**Content-Type**：`application/json`

### 3. 添加标签

在 changedetection.io 中为每个 Watch 添加对应的 source_tag 标签：
- 应急管理部 → `mem`
- 中国政府网 → `gov_cn`
- 国家法律法规数据库 → `npc`
- 国家标准公开 → `samr`

标签会被注入到 Webhook JSON 的 `source_tag` 字段，供 dazah 路由到正确的提取策略。

## dazah 侧配置

### 环境变量

在 `.env.development` 中配置：

```bash
# 启用法规抓取
SAFETY_REGULATION_CRAWLER_ENABLED=true

# 抓取间隔（小时），默认 24
SAFETY_REGULATION_CRAWLER_INTERVAL_HOURS=24

# 飞书通知目标（可选）
SAFETY_REGULATION_CRAWLER_NOTIFY_CHAT_ID=oc_xxxxxxxx
SAFETY_REGULATION_CRAWLER_NOTIFY_USERS=ou_xxx,ou_yyy
```

### 消息通知配置

- `SAFETY_REGULATION_CRAWLER_NOTIFY_CHAT_ID`：飞书群聊 ID，推送汇总通知
- `SAFETY_REGULATION_CRAWLER_NOTIFY_USERS`：飞书用户 open_id（逗号分隔），推送个人通知

## 验证

### 1. 测试 Webhook 连通性

```bash
curl -X POST http://localhost:8000/api/v1/safety/regulation-crawler/webhook/changedetection \
  -H "Content-Type: application/json" \
  -d '{
    "watch_url": "https://www.mem.gov.cn/fw/flgb/",
    "watch_title": "应急管理部法规公告",
    "current_snapshot": "<html>测试内容...</html>",
    "diff": "+ 新增一条测试法规变更内容足够长以通过实质性检测",
    "source_tag": "mem"
  }'
```

### 2. 手动触发全量抓取

```bash
curl -X POST http://localhost:8000/api/v1/safety/regulation-crawler/crawl \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 3. 检查 Bitable

打开飞书多维表格「法规标准清单」，确认新记录已创建。

## 注意事项

- changedetection.io 与 dazah 部署在同一网络内，确保网络可达
- Webhook URL 中的 `dazah-host` 需根据实际部署环境调整
- 首次配置建议先用 `--dry-run` 模式验证 Webhook 连通性
- 政府网站可能限制爬取频率，changedetection.io 的检测间隔建议 >= 6 小时
