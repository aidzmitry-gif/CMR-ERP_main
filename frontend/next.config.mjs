/** @type {import('next').NextConfig} */
const nextConfig = {
  // Прокси на backend — в route-handler'е `src/app/api/[...path]/route.ts`
  // (там же проброс dev-роли в заголовок X-User-Roles). Rewrite больше не нужен.
};

export default nextConfig;
