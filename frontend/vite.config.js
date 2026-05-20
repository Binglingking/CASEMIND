import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',   // 明确绑 IPv4，避免只在 IPv6 localhost 监听
    port: 5173,
    strictPort: true,    // 端口被占用直接报错，不要静默漂到 5174
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8888',
        changeOrigin: true,
      },
    },
  },
});
