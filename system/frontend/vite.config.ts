import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@dashboard': path.resolve(__dirname, 'src/dashboard'),
      '@viewer': path.resolve(__dirname, 'src/viewer'),
      '@maps': path.resolve(__dirname, 'src/viewer/assets/maps'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
  },
});
