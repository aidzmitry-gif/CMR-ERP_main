/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    return [{
      source: '/:path*',
      headers: [
        { key: 'Content-Security-Policy', value: "frame-ancestors 'self'" },
        { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
        { key: 'Permissions-Policy', value: 'camera=(self), microphone=(self), geolocation=(self)' },
      ],
    }];
  },
  // Прокси на backend — в route-handler'е `src/app/api/[...path]/route.ts`
  // (там же проброс dev-роли в заголовок X-User-Roles). Rewrite больше не нужен.
};

export default nextConfig;
