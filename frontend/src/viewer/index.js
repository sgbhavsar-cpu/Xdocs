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

import { highlightCode, renderMath, renderMermaid } from './enhancers.js';

// Replaced at build time with the compiled Tailwind stylesheet (build.mjs).
const STYLES = __XDOCS_CSS__;

const MOBILE_BREAKPOINT = 768;
const DEFAULT_CDN = 'https://esm.sh';

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
    // Re-apply properties set by the host before the element upgraded.
    this.#upgradeProperty('tokenProvider');
    this.#observeSize();
    this.#ready = true;
    this.#emit('xdocs:ready', { version: '0.0.1' });
    this.#init();
  }

  #upgradeProperty(prop) {
    if (Object.prototype.hasOwnProperty.call(this, prop)) {
      const value = this[prop];
      delete this[prop];
      this[prop] = value;
    }
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
          <div class="xd-search-wrap">
            <select class="xd-scope" aria-label="Search scope">
              <option value="space">This space</option>
              <option value="corpus">Everything</option>
            </select>
            <input class="xd-search" aria-label="Search" placeholder="Search…" />
            <div class="xd-results" hidden></div>
          </div>
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
        <button class="xd-toc-fab" aria-label="On this page" hidden>On this page</button>
        <div class="xd-sheet" data-open="false" role="dialog" aria-label="On this page">
          <div class="xd-sheet-handle"></div>
          <div class="xd-sheet-body"></div>
        </div>
      </div>`;

    const root = this.#shadow.querySelector('.xd-root');
    this.#shadow.querySelector('.xd-hamburger').addEventListener('click', () => {
      root.dataset.navOpen = String(root.dataset.navOpen !== 'true');
    });
    this.#shadow.querySelector('.xd-scrim').addEventListener('click', () => {
      root.dataset.navOpen = 'false';
    });
    this.#shadow.querySelector('.xd-toc-fab').addEventListener('click', () => {
      const sheet = this.#shadow.querySelector('.xd-sheet');
      sheet.dataset.open = String(sheet.dataset.open !== 'true');
    });

    // Live search (debounced) + scope selector (C4/C5).
    const input = this.#shadow.querySelector('.xd-search');
    const scope = this.#shadow.querySelector('.xd-scope');
    let timer = null;
    const trigger = () => {
      clearTimeout(timer);
      timer = setTimeout(() => this.#runSearch(input.value.trim()), 200);
    };
    input.addEventListener('input', trigger);
    scope.addEventListener('change', trigger);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this.#hideResults();
    });
    // Dismiss results when focus leaves the search area.
    this.#shadow.addEventListener('click', (e) => {
      if (!e.composedPath().includes(this.#shadow.querySelector('.xd-search-wrap'))) {
        this.#hideResults();
      }
    });
  }

  #hideResults() {
    const panel = this.#shadow.querySelector('.xd-results');
    if (panel) panel.hidden = true;
  }

  #scopeValue() {
    const scope = this.#shadow.querySelector('.xd-scope')?.value || 'space';
    return scope === 'corpus' ? 'corpus' : `space:${this.space}`;
  }

  async #runSearch(query) {
    const panel = this.#shadow.querySelector('.xd-results');
    if (!query || query.length < 2) {
      this.#hideResults();
      return;
    }
    try {
      const scope = encodeURIComponent(this.#scopeValue());
      const data = await this.#api(`/search?q=${encodeURIComponent(query)}&scope=${scope}`);
      this.#renderResults(panel, data.results || []);
      this.#emit('xdocs:search', { query, scope: this.#scopeValue() });
    } catch {
      this.#hideResults();
    }
  }

  #renderResults(panel, results) {
    panel.replaceChildren();
    if (!results.length) {
      const empty = document.createElement('div');
      empty.className = 'xd-results-empty';
      empty.textContent = 'No results';
      panel.appendChild(empty);
      panel.hidden = false;
      return;
    }
    for (const r of results) {
      const item = document.createElement('button');
      item.className = 'xd-result';
      const title = document.createElement('span');
      title.className = 'xd-result-title';
      title.textContent = r.title; // plain text (safe)
      const snip = document.createElement('span');
      snip.className = 'xd-result-snip';
      snip.innerHTML = r.snippet; // server-escaped, only <em> markup
      const meta = document.createElement('span');
      meta.className = 'xd-result-meta';
      meta.textContent = r.space;
      item.append(title, snip, meta);
      item.addEventListener('click', () => {
        this.#hideResults();
        this.#loadPage(r.page_id, r.best_anchor);
      });
      panel.appendChild(item);
    }
    panel.hidden = false;
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

  async #loadPage(pageId, anchor = null) {
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
      // Progressive enhancement (lazy-loaded, fire-and-forget): page is usable
      // immediately and upgrades as libraries arrive.
      const cdn = this.getAttribute('cdn-base') || DEFAULT_CDN;
      const dark = this.getAttribute('data-theme') === 'dark';
      highlightCode(content, this.#shadow, cdn);
      renderMermaid(content, cdn, dark);
      renderMath(content, this.#shadow, cdn);
      // Close the mobile drawer after navigation.
      this.#shadow.querySelector('.xd-root').dataset.navOpen = 'false';
      // Deep-link to a section (e.g. from a search result).
      if (anchor) {
        this.#shadow.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
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

  #tocLinksHtml(headings) {
    return headings
      .map((h) => `<a href="#${h.id}" class="lvl-${h.level}" data-anchor="${h.id}">${h.text}</a>`)
      .join('');
  }

  #onTocClick(e) {
    const a = e.target.closest('a[data-anchor]');
    if (!a) return;
    e.preventDefault();
    this.#shadow.getElementById(a.dataset.anchor)?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
    // Close the mobile bottom sheet after jumping.
    this.#shadow.querySelector('.xd-sheet').dataset.open = 'false';
  }

  #renderToc(headings) {
    const toc = this.#shadow.querySelector('.xd-toc');
    const sheetBody = this.#shadow.querySelector('.xd-sheet-body');
    const fab = this.#shadow.querySelector('.xd-toc-fab');
    const has = Boolean(headings?.length);
    fab.hidden = !has; // CSS still limits the FAB to mobile viewports

    if (!has) {
      toc.innerHTML = '';
      sheetBody.innerHTML = '';
      return;
    }
    const links = this.#tocLinksHtml(headings);
    toc.innerHTML = `<div class="xd-toc-title">On this page</div>${links}`;
    sheetBody.innerHTML = `<div class="xd-toc-title">On this page</div>${links}`;

    // One delegated handler per region (desktop TOC + mobile sheet).
    toc.onclick = (e) => this.#onTocClick(e);
    sheetBody.onclick = (e) => this.#onTocClick(e);
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
