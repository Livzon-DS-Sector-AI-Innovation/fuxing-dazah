import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  output: 'standalone',
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
};

export default nextConfig;
