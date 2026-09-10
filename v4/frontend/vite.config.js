import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: { include: ['src/**/*.test.{js,jsx}'], environment: 'jsdom', pool: 'threads', maxWorkers: 1, restoreMocks: true },
})
