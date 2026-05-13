import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,  // fail instead of bumping to next port
  },
  plugins: [react()]
})


