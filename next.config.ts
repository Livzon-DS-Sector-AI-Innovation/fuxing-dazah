import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  output: 'standalone',
  reactCompiler: true,
  allowedDevOrigins: ['*'],
};

export default nextConfig;
