"""系统设置接口"""

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access

router = APIRouter(tags=["HR-系统设置"])


@router.get("/system-settings", summary="读取系统设置")
async def get_settings(session: AsyncSession = Depends(get_db), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    from app.modules.hr.models import SystemSetting
    r = await session.execute(select(SystemSetting).where(SystemSetting.is_deleted == False))
    result = {}
    for s in r.scalars().all():
        result[s.key] = s.value
    return success_response(data=result)


@router.put("/system-settings", summary="保存系统设置")
async def save_settings(settings: dict[str, str], session: AsyncSession = Depends(get_db), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    from app.modules.hr.models import SystemSetting
    for key, value in settings.items():
        r = await session.execute(select(SystemSetting).where(SystemSetting.key == key))
        row = r.scalar_one_or_none()
        if row:
            row.value = value
        else:
            session.add(SystemSetting(key=key, value=value))
    await session.commit()
    import subprocess, json as _json
    auth_url = None; device_code = None
    new_mail = settings.get("mail_sender", "")
    if new_mail:
        try:
            r2 = subprocess.run(["lark-cli", "auth", "login", "--domain", "mail", "--no-wait", "--json"], capture_output=True, text=True, timeout=15)
            if r2.returncode == 0:
                try:
                    d = _json.loads(r2.stdout)
                    auth_url = d.get("verification_url"); device_code = d.get("device_code")
                except Exception: pass
        except FileNotFoundError:
            pass  # lark-cli 未安装，设置已保存但无法生成授权链接
    return success_response(data={"auth_url": auth_url, "device_code": device_code}, message="已保存" + (" — 请扫码授权新邮箱" if auth_url else ""))


@router.post("/system-settings/complete-auth", summary="完成邮箱授权")
async def complete_mail_auth(device_code: str = Form(...), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    import subprocess
    try:
        r = subprocess.run(["lark-cli", "auth", "login", "--device-code", device_code], capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise HTTPException(400, "lark-cli 未安装，请联系管理员在服务器上安装 lark-cli")
    if r.returncode != 0: raise HTTPException(400, r.stderr.strip() or "授权失败")
    return success_response(message="授权完成")
