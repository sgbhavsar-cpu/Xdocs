/**
 * Build the Xdocs control bundle.
 *
 * Step 1: compile Tailwind (PostCSS) to a CSS string.
 * Step 2: bundle the Web Component with esbuild, inlining that CSS via a
 *         `define` so each component can adopt it into its Shadow DOM.
 *
 * Run: `node build.mjs` (one-shot) or `node build.mjs --watch`.
 */
import { readFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import esbuild from 'esbuild';
import postcss from 'postcss';
import tailwind from 'tailwindcss';
import autoprefixer from 'autoprefixer';
import tailwindConfig from './tailwind.config.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const watch = process.argv.includes('--watch');
const outdir = resolve(__dirname, 'dist');
mkdirSync(outdir, { recursive: true });

async function compileCss() {
  const css = readFileSync(resolve(__dirname, 'src/shared/styles.css'), 'utf8');
  const result = await postcss([tailwind(tailwindConfig), autoprefixer]).process(css, {
    from: 'src/shared/styles.css',
  });
  return result.css;
}

async function build() {
  const css = await compileCss();
  const common = {
    bundle: true,
    format: 'esm',
    target: 'es2022',
    sourcemap: true,
    define: { __XDOCS_CSS__: JSON.stringify(css) },
  };

  const buildOne = (entry, outfile) =>
    esbuild.context({ ...common, entryPoints: [entry], outfile });

  const viewer = await buildOne('src/viewer/index.js', 'dist/xdocs.js');

  if (watch) {
    await viewer.watch();
    console.log('[xdocs] watching for changes…');
  } else {
    await viewer.rebuild();
    await viewer.dispose();
    console.log('[xdocs] built dist/xdocs.js');
  }
}

build().catch((err) => {
  console.error(err);
  process.exit(1);
});
