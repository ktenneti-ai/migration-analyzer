/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// GitHub Codespaces forwards the dev server over HTTPS on port 443, but the
// server itself listens on 5180 — without telling Vite's HMR client to
// connect back through the forwarded host/443 instead of localhost:5180, the
// WebSocket handshake fails, which can leave the page blank (works fine
// locally, where localhost:5180 is directly reachable).
const codespaceName = process.env.CODESPACE_NAME
const forwardingDomain = process.env.GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN ?? 'app.github.dev'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // bind 0.0.0.0 so GitHub Codespaces port forwarding can reach it
    port: 5180,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:8000',
    },
    hmr: codespaceName
      ? {
          host: `${codespaceName}-5180.${forwardingDomain}`,
          protocol: 'wss',
          clientPort: 443,
        }
      : undefined,
  },
  // `vite preview` (used to serve the app in Codespaces — see start.sh) reads
  // this block, NOT `server` above; Vite keeps the two configs separate, so
  // the /api proxy has to be repeated here or the built app loads but every
  // API call 404s.
  preview: {
    host: true,
    port: 5180,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
})
