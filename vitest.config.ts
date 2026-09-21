import { defineConfig } from 'vitest/config';

export default defineConfig({
  // Resolves the path aliases declared in tsconfig.json (natively supported by
  // Vite, which replaces the vite-tsconfig-paths plugin).
  resolve: { tsconfigPaths: true },
  test: {
    globals: true,
    root: './',
    include: ['**/*.spec.ts'],
    // Decorator metadata is read by class-transformer, class-validator and
    // TypeORM, so the polyfill has to be loaded before any spec imports them.
    setupFiles: ['reflect-metadata'],
  },
});
