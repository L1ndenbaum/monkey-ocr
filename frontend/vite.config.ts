import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const gatewayTarget = env.VITE_GATEWAY_BASE_URL || "http://localhost:13000";

  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: Number(env.VITE_FRONTEND_PORT || 13002),
      proxy: {
        "/v1": {
          target: gatewayTarget,
          changeOrigin: true,
        },
        "/health": {
          target: gatewayTarget,
          changeOrigin: true,
        },
      },
    },
    preview: {
      host: "0.0.0.0",
      port: Number(env.VITE_FRONTEND_PREVIEW_PORT || 13002),
    },
  };
});
