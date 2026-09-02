import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  turbopack: {
    root: __dirname,
  },
  reactCompiler: true,
  allowedDevOrigins: ['*', '127.0.0.1'],

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
