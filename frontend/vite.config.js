import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',   // 监听所有网络接口，局域网内可访问
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
