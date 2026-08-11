import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const isPluginBuild = mode === 'plugin' || process.env.BUILD_PLUGIN === 'true'

  if (isPluginBuild) {
    return {
      plugins: [react()],
      define: {
        'process.env.NODE_ENV': JSON.stringify('production'),
      },
      build: {
        outDir: path.resolve(__dirname, '../backend/plugin_assets'),
        emptyOutDir: false,
        lib: {
          entry: path.resolve(__dirname, 'src/plugin.jsx'),
          name: 'SbiCmsWidget',
          fileName: () => 'widget.js',
          formats: ['iife'],
        },
        rollupOptions: {
          output: {
            assetFileNames: (assetInfo) => {
              if (assetInfo.name && assetInfo.name.endsWith('.css')) {
                return 'widget.css'
              }
              return assetInfo.name || 'asset.[ext]'
            },
          },
        },
      },
    }
  }

  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy: {
        '/api': {
          target: 'http://localhost:8001',
          changeOrigin: true,
          secure: false,
        },
      },
    },
    build: {
      outDir: 'dist',
    },
  }
})
