import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["**.run.app", "127.0.0.1", "localhost"],
  experimental: {
    cpus: 1,
  },
};

export default nextConfig;
