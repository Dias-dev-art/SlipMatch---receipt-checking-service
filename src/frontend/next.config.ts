import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static files in `out/`, served by the FastAPI backend in production (one URL).
  // Every page loads its data in the browser, so nothing needs a Node server.
  output: "export",
  // `orders/index.html` instead of `orders.html`, so `/orders/` works on any static server
  trailingSlash: true,
  // cacheComponents / partialPrefetching are off: export mode does not support them
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
