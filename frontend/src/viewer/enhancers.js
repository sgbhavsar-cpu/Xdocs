/**
 * Client-side content enhancers (B5), lazily loaded from a CDN on first use so
 * the core bundle stays small (design §3.6). Each enhancer is resilient: if the
 * library fails to load, content degrades gracefully (code shows unstyled,
 * mermaid/math show their source) and no error is thrown.
 *
 * The CDN base for ES modules is configurable (`cdn-base` attribute) so hosts can
 * point at a local mirror for offline/self-hosted deployments.
 */

const CSS_HLJS = 'https://cdn.jsdelivr.net/npm/highlight.js@11/styles/github.min.css';
const CSS_KATEX = 'https://cdn.jsdelivr.net/npm/katex@0.16/dist/katex.min.css';

let _hljs;
let _mermaid;
let _katexAutoRender;

function ensureCss(shadow, id, href) {
  if (shadow.getElementById(id)) return;
  const link = document.createElement('link');
  link.id = id;
  link.rel = 'stylesheet';
  link.href = href;
  shadow.appendChild(link);
}

/** Syntax-highlight code blocks (skips mermaid fences). */
export async function highlightCode(container, shadow, cdn) {
  const targets = [...container.querySelectorAll('pre > code[class*="language-"]')].filter(
    (c) => !c.classList.contains('language-mermaid')
  );
  if (!targets.length) return;
  try {
    _hljs ??= import(`${cdn}/highlight.js@11`).then((m) => m.default);
    const hljs = await _hljs;
    ensureCss(shadow, 'xd-hljs-css', CSS_HLJS);
    for (const code of targets) {
      try {
        hljs.highlightElement(code);
      } catch {
        /* leave block unstyled */
      }
    }
  } catch {
    /* highlighting unavailable */
  }
}

/** Render ```mermaid fences to inline SVG diagrams. */
export async function renderMermaid(container, cdn, dark) {
  const blocks = [...container.querySelectorAll('pre > code.language-mermaid')];
  if (!blocks.length) return;
  try {
    _mermaid ??= import(`${cdn}/mermaid@11`).then((m) => m.default);
    const mermaid = await _mermaid;
    mermaid.initialize({
      startOnLoad: false,
      theme: dark ? 'dark' : 'default',
      securityLevel: 'strict',
    });
    let i = 0;
    for (const block of blocks) {
      i += 1;
      try {
        const { svg } = await mermaid.render(`xd-mmd-${Date.now()}-${i}`, block.textContent);
        const fig = document.createElement('div');
        fig.className = 'xd-mermaid';
        fig.innerHTML = svg;
        block.closest('pre').replaceWith(fig);
      } catch {
        /* leave fence as source */
      }
    }
  } catch {
    /* mermaid unavailable */
  }
}

/** Render LaTeX math ($…$, $$…$$) via KaTeX auto-render. */
export async function renderMath(container, shadow, cdn) {
  if (!container.textContent || !container.textContent.includes('$')) return;
  try {
    _katexAutoRender ??= import(`${cdn}/katex@0.16/contrib/auto-render`).then((m) => m.default);
    const renderMathInElement = await _katexAutoRender;
    ensureCss(shadow, 'xd-katex-css', CSS_KATEX);
    renderMathInElement(container, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$', right: '$', display: false },
      ],
      throwOnError: false,
    });
  } catch {
    /* math unavailable */
  }
}
