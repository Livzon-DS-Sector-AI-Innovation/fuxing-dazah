import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  turbopack: {
    root: __dirname,
  },
  // React Compiler 在生产构建下会使作业看板"新建计划单"等条件渲染 Modal 的
  // open 状态在数秒后自动回退（真机验收缺陷，2026-09-16；单元测试无编译器时复现不了），
  // 修复前保持关闭
  reactCompiler: false,
  // 局域网设备访问 dev 服务的白名单（只写 hostname，不带端口/scheme；裸 '*' 在
  // Next 16.2 的 matchWildcardDomain 里被显式判死，无效条目）。改动后必须完整
  // 重启 next dev——router-server 父进程持有启动时的 config 快照，Turbopack 热
  // 重启子进程不会重读（2026-10-14 实测踩坑）。IP 变了要同步改。
  allowedDevOrigins: ['localhost', '127.0.0.1', '192.168.100.7'],

  // 内部部署阶段：默认启用 sourcemap 方便定位错误；用 ENABLE_SOURCEMAPS=false 可关闭以加速构建/减小镜像
  productionBrowserSourceMaps: process.env.ENABLE_SOURCEMAPS !== 'false',

  // 记录 fetch 请求详情，方便排查后端接口问题
  logging: {
    fetches: {
      fullUrl: true,
    },
  },

  experimental: {
    // Server Action 请求体大小限制：与后端工具箱上传上限（api.py MAX_UPLOAD_BYTES=100MB）保持一致，
    // 否则 10-100MB 的文档上传会被 Next.js 在到达后端前以 413 拒绝。
    // 默认仅 1MB，不足以传输手机拍照图片（通常 3-8MB）
    serverActions: {
      bodySizeLimit: '100mb',
    },
  },

  // 三期：旧 5 个配置页 301 到 /safety/system 单页并带 ?tab= 直达对应 Tab
  // （redirects 先于文件系统路由，旧路径已删除壳页；statusCode=301 字面永久跳转，
  //   Next 的 permanent:true 是 308，任务书口径为 301 故显式指定）
  async redirects() {
    return [
      { source: '/safety/system/ai-config', destination: '/safety/system?tab=ai-models', statusCode: 301 },
      { source: '/safety/system/bitable-config', destination: '/safety/system?tab=bitable', statusCode: 301 },
      { source: '/safety/system/app-config', destination: '/safety/system?tab=app', statusCode: 301 },
      { source: '/safety/system/scheduled-tasks', destination: '/safety/system?tab=scheduler', statusCode: 301 },
      { source: '/safety/ai-audit', destination: '/safety/system?tab=ai-audits', statusCode: 301 },
    ]
  },

  // 开发环境代理 API 请求到后端，避免跨端口 cookie 问题
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      },
    ]
  },

};

export default nextConfig;
