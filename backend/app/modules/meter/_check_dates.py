import sys, json
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
data = json.load(sys.stdin)
recs = data['data']['electricity']['records']
dates = sorted([r['fields']['日期'] for r in recs], reverse=True)
now = datetime.now(CST)
today_ts = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
print(f"Today: {now.strftime('%Y-%m-%d')}, ts={today_ts}")
print("Latest 5:")
for ts in dates[:5]:
    dt = datetime.fromtimestamp(ts / 1000, tz=CST)
    m = " <-- TODAY" if ts >= today_ts else ""
    print(f"  {dt.strftime('%Y-%m-%d')}  ts={ts}{m}")
