/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const target = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${target}/api/:path*` },
      { source: "/ws/:path*", destination: `${target}/ws/:path*` },
    ];
  },
};

export default nextConfig;
