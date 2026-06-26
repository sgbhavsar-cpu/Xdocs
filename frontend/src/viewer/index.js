/**
 * <xdocs-viewer> — the embeddable documentation reader control.
 *
 * Renders the style-isolated three-pane shell, loads the space navigation tree
 * and page content from the backend (host-issued token via `tokenProvider`),
 * builds the right-hand "On this page" index with scroll-spy, enhances code
 * blocks, and adapts to a mobile drawer layout via ResizeObserver.
 *
 * Server-rendered page HTML is already sanitized (backend, design §12), so it is
 * injected directly. Client-side Mermaid/KaTeX rendering is loaded lazily in a
 * follow-up (B5); fenced mermaid/math blocks are left intact for that step.
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
  #headingObserver;
  #tree = null;
  #currentPageId = null;

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
    if (this.#ready) this.#init();
  }
  get tokenProvider() {
    return this.#tokenProvider;
  }

  get baseUrl() {
    return (this.getAttribute('base-url') || '').replace(/\/$/, '');
  }
  get space() {
    return this.getAttribute('space') || '';
  }
  get locale() {
    return this.getAttribute('locale') || 'en';
  }

  connectedCallback() {
    this.#applyTheme();
    this.#renderShell();
    this.#observeSize();
    this.#ready = true;
    this.#emit('xdocs:ready', { version: '0.0.1' });
    this.#init();
  }

  disconnectedCallback() {
    this.#resizeObserver?.disconnect();
    this.#headingObserver?.disconnect();
  }

  attributeChangedCallback(name) {
    if (!this.#ready) return;
    if (name === 'theme') this.#applyTheme();
    else if (name === 'space' || name === 'base-url' || name === 'locale') this.#init();
  }

  #emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { bubbles: true, composed: true, detail }));
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
      const root = this.#shadow.querySelector('.xd-root');
      if (root) root.dataset.mobile = String(width < MOBILE_BREAKPOINT);
    });
    this.#resizeObserver.observe(this);
  }

  async #token() {
    if (!this.#tokenProvider) throw new Error('no tokenProvider configured');
    return this.#tokenProvider();
  }

  async #api(path) {
    const token = await this.#token();
    const resp = await fetch(`${this.baseUrl}/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  #renderShell() {
    this.#shadow.innerHTML = `
      <div class="xd-root" data-mobile="false" data-nav-open="false">
        <header class="xd-header">
          <button class="xd-hamburger" aria-label="Toggle navigation">☰</button>
          <slot name="logo"><strong style="color:var(--xdocs-color-primary)">Xdocs</strong></slot>
          <input class="xd-search" aria-label="Search" placeholder="Search…" />
        </header>
        <div class="xd-body">
          <nav class="xd-nav" aria-label="Pages"><p>Loading…</p></nav>
          <main class="xd-main">
            <div class="xd-content" id="content">
              <p id="status">Initializing…</p>
            </div>
          </main>
          <aside class="xd-toc" aria-label="On this page"></aside>
        </div>
        <div class="xd-scrim"></div>
      </div>`;

    const root = this.#shadow.querySelector('.xd-root');
    this.#shadow.querySelector('.xd-hamburger').addEventListener('click', () => {
      root.dataset.navOpen = String(root.dataset.navOpen !== 'true');
    });
    this.#shadow.querySelector('.xd-scrim').addEventListener('click', () => {
      root.dataset.navOpen = 'false';
    });
  }

  #status(msg) {
    const s = this.#shadow.getElementById('status');
    if (s) s.textContent = msg;
  }

  async #init() {
    if (!this.baseUrl || !this.#tokenProvider) {
      this.#status('Not configured (set base-url and tokenProvider).');
      return;
    }
    if (!this.space) {
      this.#status('No space selected.');
      return;
    }
    try {
      await this.#api('/me'); // verify auth before loading content
      await this.#loadTree();
    } catch (err) {
      this.#status(`Connection failed: ${err.message}`);
      this.#emit('xdocs:error', { code: 'load_failed', message: err.message });
    }
  }

  async #loadTree() {
    this.#tree = await this.#api(`/spaces/${this.space}/tree?locale=${this.locale}`);
    this.#renderNav();
    const first = this.#firstPage();
    if (first) this.#loadPage(first.id);
    else this.#status('No pages in this space yet.');
  }

  #firstPage() {
    for (const book of this.#tree.books) {
      if (book.pages.length) return book.pages[0];
    }
    return null;
  }

  #renderNav() {
    const nav = this.#shadow.querySelector('.xd-nav');
    const renderPages = (pages) => {
      const items = pages
        .map(
          (p) => `
        <li>
          <button data-page="${p.id}">${p.title}</button>
          ${p.children?.length ? `<ul class="xd-children">${renderPages(p.children)}</ul>` : ''}
        </li>`
        )
        .join('');
      return items;
    };
    nav.innerHTML = this.#tree.books
      .map(
        (b) => `
        <div class="xd-book">${b.title}</div>
        <ul>${renderPages(b.pages)}</ul>`
      )
      .join('');

    nav.querySelectorAll('button[data-page]').forEach((btn) => {
      btn.addEventListener('click', () => this.#loadPage(btn.dataset.page));
    });
  }

  async #loadPage(pageId) {
    try {
      const page = await this.#api(`/pages/${pageId}?locale=${this.locale}`);
      this.#currentPageId = pageId;
      const content = this.#shadow.getElementById('content');
      const banner = page.fallback
        ? `<p style="color:var(--xdocs-color-muted);font-size:.85rem;border:1px solid var(--xdocs-color-border);padding:.5rem;border-radius:6px">
             Not available in “${page.fallback.requested_locale}”. Showing “${page.fallback.served_locale}”.
           </p>`
        : '';
      content.innerHTML = banner + page.html; // server-sanitized HTML
      this.#enhanceCode(content);
      this.#renderToc(page.headings);
      this.#highlightNav(pageId);
      this.#setupScrollSpy();
      // Close the mobile drawer after navigation.
      this.#shadow.querySelector('.xd-root').dataset.navOpen = 'false';
      this.#emit('xdocs:navigate', {
        page_id: pageId,
        space: this.space,
        locale: page.locale,
        version: page.version?.label,
        path: `${this.space}/${page.slug}`,
      });
    } catch (err) {
      this.#status(`Failed to load page: ${err.message}`);
      this.#emit('xdocs:error', { code: 'page_failed', message: err.message });
    }
  }

  #highlightNav(pageId) {
    this.#shadow.querySelectorAll('.xd-nav button[data-page]').forEach((b) => {
      b.classList.toggle('active', b.dataset.page === pageId);
    });
  }

  #enhanceCode(container) {
    container.querySelectorAll('pre > code').forEach((code) => {
      const pre = code.parentElement;
      if (pre.querySelector('.xd-copy')) return;
      const btn = document.createElement('button');
      btn.className = 'xd-copy';
      btn.textContent = 'Copy';
      btn.addEventListener('click', async () => {
        try {
          await navigator.clipboard?.writeText(code.textContent);
          btn.textContent = 'Copied';
          setTimeout(() => (btn.textContent = 'Copy'), 1200);
        } catch {
          /* clipboard unavailable */
        }
      });
      pre.appendChild(btn);
    });
  }

  #renderToc(headings) {
    const toc = this.#shadow.querySelector('.xd-toc');
    if (!headings?.length) {
      toc.innerHTML = '';
      return;
    }
    toc.innerHTML =
      `<div class="xd-toc-title">On this page</div>` +
      headings
        .map((h) => `<a href="#${h.id}" class="lvl-${h.level}" data-anchor="${h.id}">${h.text}</a>`)
        .join('');
    toc.querySelectorAll('a[data-anchor]').forEach((a) => {
      a.addEventListener('click', (e) => {
        e.preventDefault();
        const target = this.#shadow.getElementById(a.dataset.anchor);
        target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  #setupScrollSpy() {
    this.#headingObserver?.disconnect();
    const content = this.#shadow.getElementById('content');
    const headings = [...content.querySelectorAll('h2[id], h3[id], h4[id]')];
    if (!headings.length) return;
    const links = this.#shadow.querySelectorAll('.xd-toc a[data-anchor]');
    const root = this.#shadow.querySelector('.xd-main');
    this.#headingObserver = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const id = entry.target.id;
            links.forEach((l) => l.classList.toggle('active', l.dataset.anchor === id));
          }
        }
      },
      { root, rootMargin: '0px 0px -70% 0px', threshold: 0 }
    );
    headings.forEach((h) => this.#headingObserver.observe(h));
  }
}

if (!customElements.get('xdocs-viewer')) {
  customElements.define('xdocs-viewer', XdocsViewer);
}

export { XdocsViewer };
