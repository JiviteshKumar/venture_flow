import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Vendor code in its own long-lived chunks.
        //
        // The whole app used to ship as one 977 KB file (281 KB gzipped): every
        // page, the charting library and the animation library, all downloaded
        // before the sign-in screen could render. Splitting vendors lets the
        // browser cache React, the charts and the animation code across deploys
        // -- they change far less often than the app -- and lets the pages
        // themselves load on demand (see the lazy routes in App.tsx).
        //
        // Only React and the router are named. A first version also named
        // charts, motion, icons and a catch-all "vendor", and Rollup reported a
        // circular chunk (vendor -> react -> vendor) because packages in the
        // catch-all import React and are imported back. Everything else is left
        // to Rollup, which already puts recharts and its dependencies into one
        // chunk shared by the two pages that draw charts, and nowhere else.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|@remix-run[\\/]router)[\\/]/.test(id)) {
            return "react";
          }
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Proxy /api/* calls to FastAPI backend — avoids CORS issues in dev
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
