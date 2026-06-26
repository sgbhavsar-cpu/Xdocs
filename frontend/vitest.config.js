import { defineConfig } from 'vitest/config';

export default defineConfig({
  // `__XDOCS_CSS__` is injected by esbuild at build time; stub it for unit tests.
  define: { __XDOCS_CSS__: '""' },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.test.js'],
  },
});
