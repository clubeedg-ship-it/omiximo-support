import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    allowedHosts: ['support.abbamarkt.nl'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@clerk/shared/loadClerkJsScript': path.resolve(
        __dirname,
        './src/shims/clerk-load-script.ts',
      ),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
