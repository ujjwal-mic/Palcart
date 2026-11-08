// Vite is the tool that runs our React app. The react plugin lets it read JSX.
//
// PROXY: while you develop (npm run dev), any request to /api/... is forwarded
// to the Python server on port 8000. That way the page never needs to know the
// server's address, and there are no "CORS" problems.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
});
