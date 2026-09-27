import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";

const currentFile = fileURLToPath(import.meta.url);
const currentDir = path.dirname(currentFile);

export default defineConfig({
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: false,
      },
    },
  },
  build: {
    rollupOptions: {
      input: {
        game: path.resolve(currentDir, "index.html"),
        editor: path.resolve(currentDir, "editor.html"),
        generator: path.resolve(currentDir, "generator.html"),
      },
    },
  },
});
