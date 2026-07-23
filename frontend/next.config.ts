import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  turbopack: {
    root: __dirname,
  },
  reactCompiler: true,
  allowedDevOrigins: ['*', '127.0.0.1'],

  // 内部部署阶段：启用 sourcemap 方便定位错误
  productionBrowserSourceMaps: true,

  // 记录 fetch 请求详情，方便排查后端接口问题
  logging: {
    fetches: {
      fullUrl: true,
    },
  },

  experimental: {
    // Server Action 请求体大小限制（与后端 MAX_UPLOAD_SIZE_MB=10 保持一致）
    // 默认仅 1MB，不足以传输手机拍照图片（通常 3-8MB）
    serverActions: {
      bodySizeLimit: '10mb',
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

  // 旧路由重定向
  async redirects() {
    return [
      {
        source: '/production/intermediate-types',
        destination: '/production/materials',
        permanent: true,
      },
    ]
  },
};

export default nextConfig;
