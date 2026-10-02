import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies the API to the Python backend (default :8000; set SHG_API to change it,
// e.g. SHG_API=http://localhost:8203 npm run dev).
// `npm run build` writes dist/, which the backend serves at http://localhost:8000/
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": process.env.SHG_API || "http://localhost:8000" } },
});
