// Next.js 15 + ESLint 9 flat-config. eslint-config-next@16 экспортирует нативные flat-конфиги,
// поэтому FlatCompat не нужен (он несовместим с ESLint 9 и падает circular-structure).
import coreWebVitals from 'eslint-config-next/core-web-vitals'
import typescript from 'eslint-config-next/typescript'

const eslintConfig = [
  ...coreWebVitals,
  ...typescript,
  {
    ignores: ['node_modules/**', '.next/**', 'out/**', 'build/**', 'next-env.d.ts'],
  },
]

export default eslintConfig
