"""离职证明公开签署接口（无需登录）。GET 返回 HTML 页面，POST 提交签署。"""

import json as _json
from datetime import datetime as dt, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter(tags=["离职证明签署"])


SIGN_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>离职证明签署</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f0f2f5;min-height:100vh;display:flex;align-items:center;justify-content:center}}
.card{{background:#fff;border-radius:12px;padding:32px 24px;max-width:420px;width:100%;margin:16px;box-shadow:0 2px 8px rgba(0,0,0,0.1)}}
h2{{text-align:center;margin-bottom:20px;color:#1a1a1a}}
.info{{background:#f5f5f5;border-radius:8px;padding:12px 16px;margin-bottom:20px;line-height:1.8}}
.info strong{{color:#333}} .info span{{color:#666;font-size:14px}}
label{{display:block;margin-bottom:4px;font-weight:600;font-size:14px;color:#333}}
input{{width:100%;padding:10px 12px;border:1px solid #d9d9d9;border-radius:8px;font-size:16px;margin-bottom:16px}}
input:focus{{outline:none;border-color:#1677ff;box-shadow:0 0 0 2px rgba(22,119,255,0.2)}}
canvas{{border:1px solid #d9d9d9;border-radius:8px;width:100%;cursor:crosshair;touch-action:none;display:block}}
.btn{{width:100%;padding:12px;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer}}
.btn-primary{{background:#1677ff;color:#fff;margin-top:16px}}
.btn-primary:disabled{{background:#91caff;cursor:not-allowed}}
.btn-clear{{background:#fff;color:#666;border:1px solid #d9d9d9;margin-top:8px}}
.status{{text-align:center;padding:48px 0}}
.status h2{{font-size:20px}} .status p{{color:#666;margin-top:12px}}
.loading{{text-align:center;padding:48px 0;color:#999}}
.error{{text-align:center;padding:48px 0;color:#ff4d4f}}
</style>
</head>
<body>
<div class="card" id="app"><div class="loading">加载中...</div></div>
<script>
var token = window.location.pathname.split('/').pop();
var apiBase = window.location.pathname.replace('/public/','/api/v1/public/');

async function load() {{
  try {{
    var r = await fetch(apiBase + '/data');
    var d = await r.json();
    if (d.code !== 200) {{ showError(d.message || '链接无效'); return; }}
    if (d.data.sign_status === 'signed') {{ showSigned(); return; }}
    showForm(d.data);
  }} catch(e) {{ showError('网络错误'); }}
}}

function showError(msg) {{
  document.getElementById('app').innerHTML = '<div class="error"><h3>签署链接无效</h3><p>'+msg+'</p></div>';
}}

function showSigned() {{
  document.getElementById('app').innerHTML = '<div class="status"><h2 style="color:#52c41a">&#10003; 已完成签署</h2><p>离职证明已发送至您的邮箱，请查收。</p></div>';
}}

function showForm(data) {{
  document.getElementById('app').innerHTML =
    '<h2>离职证明签署</h2>' +
    '<div class="info"><strong>'+data.name+'</strong><br>' +
    '<span>'+data.department+' &middot; '+data.position+'</span><br>' +
    '<span>离职日期：'+data.offboarding_date+'</span></div>' +
    '<label>确认姓名</label><input id="fname" placeholder="请输入您的姓名">' +
    '<label>身份证后四位</label><input id="fid" placeholder="身份证后四位" maxlength="4" type="text" inputmode="numeric" pattern="[0-9]*">' +
    '<label>手写签名</label><canvas id="sigpad" width="400" height="150"></canvas>' +
    '<button class="btn btn-clear" onclick="clearSig()">清除重签</button>' +
    '<button class="btn btn-primary" id="submitBtn" onclick="doSign()">确认签署</button>';
  initCanvas();
}}

function initCanvas() {{
  var c = document.getElementById('sigpad'); if(!c) return;
  var ctx = c.getContext('2d'); ctx.lineWidth=2; ctx.strokeStyle='#000'; ctx.lineCap='round';
  var drawing = false;
  function getPos(e) {{
    var r = c.getBoundingClientRect(), t = e.touches ? e.touches[0] : e;
    return {{x:(t.clientX-r.left)*(c.width/r.width), y:(t.clientY-r.top)*(c.height/r.height)}};
  }}
  c.addEventListener('mousedown',function(e){{e.preventDefault();drawing=true;var p=getPos(e);ctx.beginPath();ctx.moveTo(p.x,p.y)}});
  c.addEventListener('mousemove',function(e){{e.preventDefault();if(!drawing)return;var p=getPos(e);ctx.lineTo(p.x,p.y);ctx.stroke()}});
  c.addEventListener('mouseup',function(){{drawing=false;ctx.closePath()}});
  c.addEventListener('mouseleave',function(){{drawing=false}});
  c.addEventListener('touchstart',function(e){{e.preventDefault();drawing=true;var p=getPos(e);ctx.beginPath();ctx.moveTo(p.x,p.y)}});
  c.addEventListener('touchmove',function(e){{e.preventDefault();if(!drawing)return;var p=getPos(e);ctx.lineTo(p.x,p.y);ctx.stroke()}});
  c.addEventListener('touchend',function(){{drawing=false;ctx.closePath()}});
}}

function clearSig() {{
  var c=document.getElementById('sigpad'); if(!c) return;
  c.getContext('2d').clearRect(0,0,c.width,c.height);
}}

function hasSig() {{
  var c=document.getElementById('sigpad'); if(!c) return false;
  var d=c.getContext('2d').getImageData(0,0,c.width,c.height);
  for(var i=0;i<d.data.length;i+=4) if(d.data[i+3]>0) return true;
  return false;
}}

async function doSign() {{
  var name=document.getElementById('fname').value.trim();
  var id4=document.getElementById('fid').value.trim();
  if(!name){{alert('请输入姓名');return}}
  if(id4.length!==4||!/^\\d{{4}}$/.test(id4)){{alert('请输入4位数字身份证后四位');return}}
  if(!hasSig()){{alert('请在签名区手写签名');return}}
  var img=document.getElementById('sigpad').toDataURL('image/png');
  var btn=document.getElementById('submitBtn'); btn.disabled=true; btn.textContent='提交中...';
  try {{
    var r=await fetch(apiBase,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name:name,id_card_last4:id4,sign_image:img}})}});
    var d=await r.json();
    if(r.ok){{ document.getElementById('app').innerHTML='<div class="status"><h2 style="color:#52c41a">&#10003; 签署成功</h2><p>离职证明已发送至您的邮箱，请查收。</p></div>'; }}
    else {{ alert(d.message||'签署失败'); btn.disabled=false; btn.textContent='确认签署'; }}
  }} catch(e) {{ alert('网络错误'); btn.disabled=false; btn.textContent='确认签署'; }}
}}

load();
</script>
</body>
</html>"""


@router.get("/certificate-sign/{token}", response_class=HTMLResponse)
async def sign_page(token: str, session: AsyncSession = Depends(get_db)):
    """员工点邮件链接后看到的签署页面。"""
    from app.modules.hr.models import DepartureRecord
    record = (await session.execute(
        select(DepartureRecord).where(
            DepartureRecord.cert_sign_token == token,
            DepartureRecord.is_deleted == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not record:
        return HTMLResponse(SIGN_PAGE.replace("load()", 'showError("签署链接无效或已过期")'), status_code=404)
    if record.cert_sign_status == "signed":
        return HTMLResponse(SIGN_PAGE.replace("load()", "showSigned()"))
    return HTMLResponse(SIGN_PAGE)


@router.get("/certificate-sign/{token}/data")
async def sign_data(token: str, session: AsyncSession = Depends(get_db)):
    """签署数据 JSON 接口（页面 JS fetch 调用）。"""
    from app.modules.hr.models import DepartureRecord
    record = (await session.execute(
        select(DepartureRecord).where(
            DepartureRecord.cert_sign_token == token,
            DepartureRecord.is_deleted == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not record:
        return JSONResponse({"code": 404, "message": "签署链接无效或已过期"})
    return JSONResponse({"code": 200, "data": {
        "name": record.name,
        "department": record.department,
        "position": record.position,
        "offboarding_date": str(record.offboarding_date) if record.offboarding_date else "",
        "sign_status": record.cert_sign_status or "pending",
    }})


@router.post("/certificate-sign/{token}")
async def sign_submit(token: str, request: Request, session: AsyncSession = Depends(get_db)):
    """员工提交签署。"""
    from app.modules.hr.models import DepartureRecord, Employee
    from app.modules.hr.mail_service import send_email
    from app.modules.hr.termination_certificate_generator import generate_termination_certificate_pdf

    body = await request.json()
    name = (body.get("name") or "").strip()
    id4 = (body.get("id_card_last4") or "").strip()
    sign_image = body.get("sign_image") or ""

    record = (await session.execute(
        select(DepartureRecord).where(
            DepartureRecord.cert_sign_token == token,
            DepartureRecord.is_deleted == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not record:
        return JSONResponse({"message": "签署链接无效或已过期"}, status_code=404)
    if record.cert_sign_status == "signed":
        return JSONResponse({"message": "已签署过"}, status_code=400)

    # 身份验证
    if record.name != name:
        return JSONResponse({"message": "姓名验证失败"}, status_code=400)
    if not record.id_card or record.id_card[-4:] != id4:
        return JSONResponse({"message": "身份证验证失败"}, status_code=400)

    # 保存签名
    record.cert_sign_status = "signed"
    record.cert_signed_at = dt.now(timezone.utc)
    record.cert_sign_image = sign_image
    record.cert_sign_name = name
    await session.flush()

    # 生成 PDF
    entry_date = record.livo_entry_date or record.factory_entry_date or ""
    pdf_buf = generate_termination_certificate_pdf(
        name=record.name or "", id_number=record.id_card or "",
        department=record.department or "", position=record.position or "",
        entry_date=entry_date or "", leave_date=record.offboarding_date or "",
        leave_reason=record.offboarding_type or "个人原因",
    )

    # 查邮箱并发邮件
    emp_email = (await session.execute(
        select(Employee.email).where(Employee.name == record.name, Employee.is_deleted == False)
    )).scalar_one_or_none()
    if emp_email:
        try:
            await send_email(
                to=emp_email,
                subject=f"离职证明 - {record.name}",
                html_body=f"{record.name}，您好：<br><br>您的离职证明已生成，请查收附件。<br><br>丽珠集团福州福兴医药有限公司",
                attachments=[("离职证明.pdf", pdf_buf.read())],
                session=session,
            )
        except Exception:
            pass

    await session.commit()
    return JSONResponse({"message": "签署成功"}, status_code=200)
