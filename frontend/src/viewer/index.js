/**
 * <xdocs-viewer> — the embeddable documentation reader control.
 *
 * Phase 0 walking skeleton: mounts the three-pane shell in a style-isolated
 * Shadow DOM, applies theme tokens, wires the host-provided `tokenProvider`,
 * verifies the auth flow against the backend (`/me`), emits lifecycle events,
 * and switches to a mobile layout via ResizeObserver. Content/search/LLM panes
 * are filled in during Epics B–D.
 */

// Replaced at build time with the compiled Tailwind stylesheet (build.mjs).
const STYLES = __XDOCS_CSS__;

const MOBILE_BREAKPOINT = 768;

class XdocsViewer extends HTMLElement {
  static get observedAttributes() {
    return ['base-url', 'space', 'locale', 'theme'];
  }

  #shadow;
  #tokenProvider = null;
  #ready = false;
  #resizeObserver;

  constructor() {
    super();
    this.#shadow = this.attachShadow({ mode: 'open' });
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(STYLES);
    this.#shadow.adoptedStyleSheets = [sheet];
  }

  /** Host supplies an async function returning a fresh JWT. */
  set tokenProvider(fn) {
    this.#tokenProvider = fn;
    if (this.#ready) this.#verifyAuth();
  }

  get tokenProvider() {
    return this.#tokenProvider;
  }

  get baseUrl() {
    return this.getAttribute('base-url') || '';
  }

  connectedCallback() {
    this.#applyTheme();
    this.#render();
    this.#observeSize();
    this.#ready = true;
    this.dispatchEvent(
      new CustomEvent('xdocs:ready', { bubbles: true, composed: true, detail: { version: '0.0.1' } })
    );
    this.#verifyAuth();
  }

  disconnectedCallback() {
    this.#resizeObserver?.disconnect();
  }

  attributeChangedCallback(name) {
    if (!this.#ready) return;
    if (name === 'theme') this.#applyTheme();
    else this.#render();
  }

  #applyTheme() {
    const theme = this.getAttribute('theme') || 'auto';
    const dark =
      theme === 'dark' ||
      (theme === 'auto' && window.matchMedia?.('(prefers-color-scheme: dark)').matches);
    this.setAttribute('data-theme', dark ? 'dark' : 'light');
  }

  #observeSize() {
    this.#resizeObserver = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? this.clientWidth;
      const root = this.#shadow.getElementById('root');
      if (root) root.dataset.mobile = String(width < MOBILE_BREAKPOINT);
    });
    this.#resizeObserver.observe(this);
  }

  async #verifyAuth() {
    const status = this.#shadow.getElementById('status');
    if (!this.baseUrl || !this.#tokenProvider) {
      if (status) status.textContent = 'Not configured (set base-url and tokenProvider).';
      return;
    }
    try {
      const token = await this.#tokenProvider();
      const resp = await fetch(`${this.baseUrl}/api/v1/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const me = await resp.json();
      if (status)
        status.textContent = `Connected as ${me.email || me.sub} (${me.global_permission || 'no role'})`;
    } catch (err) {
      if (status) status.textContent = `Auth/connection failed: ${err.message}`;
      this.dispatchEvent(
        new CustomEvent('xdocs:error', {
          bubbles: true,
          composed: true,
          detail: { code: 'auth_failed', message: err.message },
        })
      );
    }
  }

  #render() {
    const space = this.getAttribute('space') || '—';
    this.#shadow.innerHTML = `
      <div id="root" class="min-h-[320px] flex flex-col">
        <header class="flex items-center gap-3 px-4 h-12 border-b border-xdocs-border bg-xdocs-surface">
          <slot name="logo"><span class="font-semibold text-xdocs-primary">Xdocs</span></slot>
          <span class="text-sm text-xdocs-muted">space: ${space}</span>
          <div class="ml-auto text-sm text-xdocs-muted">
            <input aria-label="Search" placeholder="Search…"
              class="px-2 py-1 rounded-xdocs border border-xdocs-border bg-xdocs-bg" />
          </div>
        </header>
        <div class="grid grid-cols-1 md:grid-cols-[260px_1fr] lg:grid-cols-[260px_1fr_240px] flex-1">
          <nav aria-label="Pages" class="hidden md:block border-r border-xdocs-border p-3 text-sm">
            <p class="text-xdocs-muted">Left index (page tree) — Epic B</p>
          </nav>
          <main class="p-6">
            <h1 class="text-2xl font-semibold mb-2">Documentation</h1>
            <p class="text-xdocs-muted mb-4">Center content (markdown) — Epic B.</p>
            <p id="status" class="text-sm">Initializing…</p>
          </main>
          <aside aria-label="On this page" class="hidden lg:block border-l border-xdocs-border p-3 text-sm">
            <p class="text-xdocs-muted">Right index (headings) — Epic B</p>
          </aside>
        </div>
      </div>`;
  }
}

if (!customElements.get('xdocs-viewer')) {
  customElements.define('xdocs-viewer', XdocsViewer);
}

export { XdocsViewer };
