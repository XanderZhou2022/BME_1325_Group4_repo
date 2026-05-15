import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Vite configuration for the EDSim React frontend.
 *
 * Adapted for standalone use in the current project.
 * Maps are now served locally from 'src/assets/maps'.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      // Changed from external relative path to local standalone assets
      '@maps': path.resolve(
        __dirname,
        'src/assets/maps'
      )
    }
  },
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
    fs: {
      // Allow serving files from the local asset tree
      allow: [
        path.resolve(__dirname),
        path.resolve(__dirname, 'src/assets/maps')
      ]
    }
  },
  preview: {
    port: 4173,
    strictPort: true,
    host: '127.0.0.1'
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    target: 'es2022'
  }
});
