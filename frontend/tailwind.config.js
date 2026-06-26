/**
 * Tailwind config for the Xdocs control. The compiled stylesheet is injected
 * into each component's Shadow DOM (see build.mjs), so utilities are scoped to
 * the control and never leak to / from the host page. Colors map onto CSS
 * custom properties so hosts can theme via `--xdocs-*` tokens (design §3.7).
 */
export default {
  content: ['./src/**/*.{js,html}'],
  theme: {
    extend: {
      colors: {
        'xdocs-bg': 'var(--xdocs-color-bg, #ffffff)',
        'xdocs-fg': 'var(--xdocs-color-fg, #1f2937)',
        'xdocs-primary': 'var(--xdocs-color-primary, #0b5cad)',
        'xdocs-muted': 'var(--xdocs-color-muted, #6b7280)',
        'xdocs-border': 'var(--xdocs-color-border, #e5e7eb)',
        'xdocs-surface': 'var(--xdocs-color-surface, #f9fafb)',
      },
      fontFamily: {
        sans: 'var(--xdocs-font-sans, ui-sans-serif, system-ui, sans-serif)',
      },
      borderRadius: {
        xdocs: 'var(--xdocs-radius, 8px)',
      },
    },
  },
  plugins: [],
};
