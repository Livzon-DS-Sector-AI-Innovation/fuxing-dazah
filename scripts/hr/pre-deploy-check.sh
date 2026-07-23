#!/bin/bash
# ============================================================
# 部署前自动检查脚本 (macOS/Linux 兼容)
# 用法: bash scripts/pre-deploy-check.sh
# ============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0

pass() { echo -e "  ${GREEN}✅ $1${NC}"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}❌ $1${NC}"; FAIL=$((FAIL+1)); }
warn() { echo -e "  ${YELLOW}⚠️  $1${NC}"; WARN=$((WARN+1)); }
section() { echo -e "\n${YELLOW}━━━ $1 ━━━${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# ─────────────────────────────────────────────
section "1. 后端 Alembic 迁移检查（CI 阻断项）"
# ─────────────────────────────────────────────
cd "$BACKEND_DIR"
HEAD_COUNT=$(.venv/bin/alembic heads 2>/dev/null | grep -c '[a-f0-9]\{12\}' || echo 0)
if [ "$HEAD_COUNT" -eq 1 ]; then
    pass "Alembic heads = 1"
else
    fail "Alembic heads = $HEAD_COUNT（必须为 1），运行 alembic merge heads"
fi

# ─────────────────────────────────────────────
section "2. 后端 Python 导入检查"
# ─────────────────────────────────────────────
cd "$BACKEND_DIR"
IMPORT_OUTPUT=$(.venv/bin/python -c "
from app.modules.hr.api import router
from app.modules.hr.service import EmployeeService
from app.modules.hr.permissions import PERMISSIONS
from app.modules.hr.training_record_generator import generate_training_record
from app.modules.hr.work_permit_generator import generate_work_permit
print(f'OK|{len(router.routes)}|{len(PERMISSIONS)}')
" 2>&1)

if echo "$IMPORT_OUTPUT" | grep -q "^OK|"; then
    ROUTES=$(echo "$IMPORT_OUTPUT" | cut -d'|' -f2 | tail -1)
    PERMS=$(echo "$IMPORT_OUTPUT" | cut -d'|' -f3 | tail -1)
    pass "所有 HR 模块导入成功 (${ROUTES} routes, ${PERMS} permissions)"
else
    fail "Python 导入失败"
fi

# ─────────────────────────────────────────────
section "3. 前端构建检查（CI 阻断项）"
# ─────────────────────────────────────────────
cd "$FRONTEND_DIR"
if pnpm build > /tmp/predeploy-build.log 2>&1; then
    pass "前端 build 成功"
else
    fail "前端 build 失败，查看 /tmp/predeploy-build.log"
    tail -20 /tmp/predeploy-build.log
fi

# ─────────────────────────────────────────────
section "4. 模板文件完整性"
# ─────────────────────────────────────────────
cd "$BACKEND_DIR"
for tpl in \
    "新员工培训计划-模板.docx" \
    "新员工培训记录-模板.docx" \
    "上岗证模板.docx" \
    "7.3新员工入职培训记录.docx" \
    "7.4培训通知书.docx" \
    "7.5培训签到表.docx" \
    "7.11培训效果评估表.docx" \
    "试卷模板.docx" \
    "roster_template.docx" \
    "offer_template.docx" \
    "company_logo.png" \
    "company_stamp.png"
do
    if [ -f "assets/hr/$tpl" ]; then
        pass "模板存在: $tpl"
    else
        fail "模板缺失: assets/hr/$tpl"
    fi
done

# ─────────────────────────────────────────────
section "5. 生产环境配置检查"
# ─────────────────────────────────────────────
cd "$FRONTEND_DIR"
if grep -q "output.*standalone" next.config.ts 2>/dev/null; then
    pass "next.config.ts: output=standalone"
else
    fail "next.config.ts: 缺少 output: 'standalone'"
fi

if grep -q "ARG NEXT_PUBLIC_API_BASE_URL" Dockerfile 2>/dev/null; then
    pass "Dockerfile: NEXT_PUBLIC_API_BASE_URL build arg 已配置"
else
    warn "Dockerfile: 建议加 ARG NEXT_PUBLIC_API_BASE_URL"
fi

cd "$BACKEND_DIR"
if grep -q "./uploads:" docker-compose.yml 2>/dev/null; then
    pass "docker-compose: uploads 目录已挂载"
else
    warn "docker-compose: uploads 未挂载，简历重启丢失"
fi

# ─────────────────────────────────────────────
section "6. 权限完整性（Python 检查）"
# ─────────────────────────────────────────────
cd "$BACKEND_DIR"
PERM_CHECK=$(.venv/bin/python -c "
import re, os
deps = open('app/modules/hr/deps.py').read()
perms_file = open('app/modules/hr/permissions.py').read()
deps_perms = set(re.findall(r'\"(hr:[a-z]+:[a-z]+)\"', deps))
defined_perms = set(re.findall(r'\"(hr:[a-z]+:[a-z_]+)\"', perms_file))
missing = deps_perms - defined_perms
for m in sorted(missing):
    print(f'MISSING:{m}')
print(f'OK|{len(deps_perms)}|{len(defined_perms)}')
" 2>&1)

MISSING_COUNT=0
while IFS= read -r line; do
    case "$line" in
        MISSING:*) fail "权限缺失: ${line#MISSING:}" ; MISSING_COUNT=$((MISSING_COUNT+1)) ;;
        OK*)
            TOTAL=$(echo "$line" | cut -d'|' -f2)
            DEFINED=$(echo "$line" | cut -d'|' -f3)
            pass "权限完整 (deps 引用 ${TOTAL} 个, permissions 定义 ${DEFINED} 个)"
            ;;
    esac
done <<< "$PERM_CHECK"

# ─────────────────────────────────────────────
section "7. 菜单路由完整性（Python 检查）"
# ─────────────────────────────────────────────
cd "$FRONTEND_DIR"
ROUTE_CHECK=$(python3 -c "
import re, os
menu = open('src/lib/menu-config.ts').read()
paths = set(re.findall(r'\"path\":\s*\"([^\"]+)\"', menu))
missing = []
for p in sorted(paths):
    if not p: continue
    target = f'src/app/(dashboard){p}/page.tsx'
    if not os.path.exists(target):
        missing.append(f'{p} -> {target}')
if missing:
    for m in missing[:10]:
        print(f'MISSING:{m}')
    if len(missing) > 10:
        print(f'MORE:{len(missing)-10}')
else:
    print('OK')
" 2>&1)

MENU_OK=true
while IFS= read -r line; do
    case "$line" in
        MISSING:*) warn "缺页面: ${line#MISSING:}" ; MENU_OK=false ;;
        MORE:*) warn "还有 ${line#MORE:} 个页面缺失" ;;
        OK) ;;
        *) ;;
    esac
done <<< "$ROUTE_CHECK"
if $MENU_OK; then
    pass "所有菜单路径都有对应页面"
fi

# ─────────────────────────────────────────────
section "8. 孤儿模板文件"
# ─────────────────────────────────────────────
cd "$BACKEND_DIR"
ORPHAN=0
for f in assets/hr/*.docx assets/hr/*.xlsx; do
    [ -f "$f" ] || continue
    fname=$(basename "$f")
    if ! grep -rq "$fname" app/ --include="*.py" 2>/dev/null; then
        warn "疑似孤儿: assets/hr/$fname"
        ORPHAN=$((ORPHAN+1))
    fi
done
if [ "$ORPHAN" -eq 0 ]; then
    pass "无孤儿模板文件"
fi

# ─────────────────────────────────────────────
section "9. 硬编码地址检查（Python 检查）"
# ─────────────────────────────────────────────
cd "$BACKEND_DIR"
BE_LOCAL=$(python3 -c "
import os, re
issues = []
for root, dirs, files in os.walk('app/modules/hr'):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for fn in files:
        if not fn.endswith('.py'): continue
        fp = os.path.join(root, fn)
        for i, line in enumerate(open(fp), 1):
            if 'localhost:8000' in line and 'NEXT_PUBLIC' not in line and 'API_BASE' not in line:
                # Skip comments and known-safe patterns
                if line.strip().startswith('#') or line.strip().startswith('//'): continue
                if 'env' in line.lower() or 'config' in line.lower() or 'get_settings' in line.lower(): continue
                if 'router' in line.lower() or 'default' in line: continue
                issues.append(f'{fp}:{i}')
print(len(issues))
" 2>&1)
if [ "$BE_LOCAL" = "0" ]; then
    pass "后端无硬编码 localhost"
else
    warn "后端有 $BE_LOCAL 处可能硬编码 localhost"
fi

cd "$FRONTEND_DIR"
FE_LOCAL=$(python3 -c "
import os, re
count = 0
for root, dirs, files in os.walk('src'):
    dirs[:] = [d for d in dirs if d != 'node_modules']
    for fn in files:
        if not (fn.endswith('.tsx') or fn.endswith('.ts')): continue
        fp = os.path.join(root, fn)
        for line in open(fp):
            if 'localhost:8000' in line and 'NEXT_PUBLIC' not in line and 'API_BASE' not in line:
                if 'localhost:8000' in line and '||' in line: continue  # fallback pattern
                count += 1
print(count)
" 2>&1)
if [ "$FE_LOCAL" = "0" ]; then
    pass "前端无硬编码 localhost"
else
    warn "前端有 $FE_LOCAL 处可能硬编码 localhost"
fi

# ─────────────────────────────────────────────
section "10. Docker 构建模拟（可选）"
# ─────────────────────────────────────────────
if command -v docker &> /dev/null && docker info &> /dev/null 2>&1; then
    warn "Docker 可用但跳过构建（耗时），手动执行："
    echo "    cd frontend && docker build --build-arg NEXT_PUBLIC_API_BASE_URL=http://192.168.3.100:8000 -t dazah-frontend:test ."
    echo "    cd backend && docker compose build app"
else
    warn "Docker 不可用，跳过构建测试"
fi

# ─────────────────────────────────────────────
echo ""
echo -e "${YELLOW}════════════════════════════════════════${NC}"
printf "  结果: ${GREEN}%s 通过${NC}  ${RED}%s 失败${NC}  ${YELLOW}%s 警告${NC}\n" "$PASS" "$FAIL" "$WARN"
if [ "$FAIL" -gt 0 ]; then
    echo -e "  ${RED}有 ${FAIL} 项必须修复后再部署！${NC}"
    exit 1
else
    echo -e "  ${GREEN}检查通过，可以部署 🚀${NC}"
fi
