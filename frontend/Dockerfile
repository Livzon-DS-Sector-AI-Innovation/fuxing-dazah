# ============================================
# 阶段 1：构建
# ============================================
FROM node:22-alpine AS builder

# 启用 pnpm（corepack 自动读取 package.json 中的 packageManager 版本）
RUN corepack enable

# 配置国内镜像源（加速依赖下载）
RUN pnpm config set registry https://registry.npmmirror.com

WORKDIR /app

# 先复制依赖文件，利用 Docker 缓存层
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

# sharp 的二进制包也走国内镜像
ENV SHARP_DIST_BASE_URL=https://npmmirror.com/mirrors/sharp

RUN pnpm install --frozen-lockfile

# API 地址（构建时 bake 进 JS + rewrite 代理），默认值可通过 docker compose build --build-arg 覆盖
ARG NEXT_PUBLIC_API_BASE_URL=http://192.168.3.100:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ARG API_BASE_URL=http://192.168.3.100:8000
ENV API_BASE_URL=${API_BASE_URL}

# 复制源码（.env.production 中的值会被 ARG/ENV 覆盖）
COPY . .

# 执行构建（产生 .next/standalone/）
RUN pnpm build

# ============================================
# 阶段 2：运行
# ============================================
FROM node:22-alpine AS runner

WORKDIR /app

# 安全：用非 root 用户运行
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# 从构建阶段复制 standalone 产物
COPY --from=builder /app/.next/standalone ./

# standalone 默认在内部找 .next/static，需要把静态资源复制进去
COPY --from=builder /app/.next/static ./.next/static

# public 目录（favicon 等）
COPY --from=builder /app/public ./public

# 切换到非 root 用户
USER nextjs

EXPOSE 3000

# API_BASE_URL 是服务端变量，运行时通过 docker run -e 或 docker-compose environment 覆盖
ENV API_BASE_URL=http://192.168.3.100:8000

CMD ["node", "server.js"]
