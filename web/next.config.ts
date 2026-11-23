import type { NextConfig } from "next";

const config: NextConfig = {
  serverExternalPackages: ["@electric-sql/pglite"],
  poweredByHeader: false,
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default config;
