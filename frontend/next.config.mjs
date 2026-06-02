/** @type {import('next').NextConfig} */
const nextConfig = {
  // Прокси на бэкенд FastAPI (понадобится при подключении к API).
  async rewrites() {
    return [{ source: "/api/:path*", destination: "http://localhost:8000/:path*" }];
  },
};

export default nextConfig;
