import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  base: './',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: 'static-review-build',
    emptyOutDir: true,
    assetsDir: '.',
    cssCodeSplit: false,
    chunkSizeWarningLimit: 2_500,
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
})
