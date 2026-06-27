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

import { mountDevPanel } from '../shared/devpanel.js';
import { t } from '../shared/i18n.js';
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
  #answerId = null;
  #version = null;
  #canEdit = false;

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
    this.#mountDevPanel();
    this.#init();
  }

  /** ISDEV=1: a runtime config panel (space/version/theme/colour overrides). */
  #mountDevPanel() {
    mountDevPanel(this, this.#shadow, {
      fetchSpaces: async () => (await this.#api('/spaces')).items || [],
    });
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
    else if (name === 'locale') {
      this.#applyI18n();
      this.#init();
    } else if (name === 'space' || name === 'base-url') this.#init();
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
          <select class="xd-version" aria-label="Version" hidden></select>
          <select class="xd-lang" aria-label="Language" hidden></select>
          <div class="xd-search-wrap">
            <select class="xd-scope" aria-label="Search scope">
              <option value="space">This space</option>
              <option value="corpus">Everything</option>
            </select>
            <input class="xd-search" aria-label="Search" placeholder="Search…" />
            <div class="xd-results" hidden></div>
          </div>
          <button class="xd-ask-btn" aria-label="Ask the docs">🤖 Ask</button>
          <button class="xd-export-btn" aria-label="Export page as PDF">⤓ PDF</button>
          <button class="xd-edit-btn" aria-label="Edit this page" hidden>✎ Edit</button>
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
        <div class="xd-ask" data-open="false" role="dialog" aria-label="Ask the docs">
          <div class="xd-ask-head">
            <strong>Ask the docs</strong>
            <select class="xd-ask-scope" aria-label="Ask scope">
              <option value="space">This space</option>
              <option value="corpus">Everything</option>
            </select>
            <button class="xd-ask-close" aria-label="Close">✕</button>
          </div>
          <div class="xd-ask-body">
            <div class="xd-ask-answer" aria-live="polite"></div>
            <div class="xd-ask-cites"></div>
            <div class="xd-ask-fb" hidden>
              <button class="xd-fb" data-r="up" aria-label="Helpful">👍</button>
              <button class="xd-fb" data-r="down" aria-label="Not helpful">👎</button>
              <button class="xd-ask-summary">Summarize this page</button>
            </div>
          </div>
          <form class="xd-ask-form">
            <input class="xd-ask-input" aria-label="Your question" placeholder="Ask a question…" />
            <button type="submit">Send</button>
          </form>
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

    // Ask panel (D3).
    const ask = this.#shadow.querySelector('.xd-ask');
    this.#shadow.querySelector('.xd-ask-btn').addEventListener('click', () => {
      ask.dataset.open = 'true';
      this.#shadow.querySelector('.xd-ask-input').focus();
    });
    this.#shadow.querySelector('.xd-ask-close').addEventListener('click', () => {
      ask.dataset.open = 'false';
    });
    this.#shadow.querySelector('.xd-ask-form').addEventListener('submit', (e) => {
      e.preventDefault();
      this.#ask(this.#shadow.querySelector('.xd-ask-input').value.trim());
    });
    ask.querySelectorAll('.xd-fb').forEach((btn) => {
      btn.addEventListener('click', () => this.#sendFeedback(btn.dataset.r));
    });
    this.#shadow.querySelector('.xd-ask-summary').addEventListener('click', () => {
      this.#summarizePage();
    });

    // Version + language switchers (G1/G3).
    this.#shadow.querySelector('.xd-version').addEventListener('change', (e) => {
      this.#version = e.target.value;
      this.#loadTree();
    });
    this.#shadow.querySelector('.xd-lang').addEventListener('change', (e) => {
      this.setAttribute('locale', e.target.value); // triggers reload + relabel
    });
    this.#applyI18n();

    this.#shadow.querySelector('.xd-export-btn').addEventListener('click', () => {
      if (this.#currentPageId) {
        this.#downloadExport({ type: 'page', id: this.#currentPageId }, 'page.pdf').catch(() => {});
      }
    });

    // Edit hands off to the host, which swaps in the authoring surface for the
    // page currently being read (shown only when the user has write access).
    this.#shadow.querySelector('.xd-edit-btn').addEventListener('click', () => {
      this.#emit('xdocs:edit', { space: this.space, pageId: this.#currentPageId });
    });
  }

  async #downloadExport(scope, filename) {
    const token = await this.#token();
    const job = await (
      await fetch(`${this.baseUrl}/api/v1/export`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope, locale: this.locale }),
      })
    ).json();
    if (job.status !== 'done' || !job.url) throw new Error('export failed');
    // The URL is signed + time-limited, so it downloads without an auth header.
    const url = `${this.baseUrl}${job.url}`;
    this.#emit('xdocs:export', { url, filename });
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
  }

  #askScope() {
    const v = this.#shadow.querySelector('.xd-ask-scope')?.value || 'space';
    return v === 'corpus' ? 'corpus' : `space:${this.space}`;
  }

  #parseSseBlock(block) {
    let event = null;
    let data = null;
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) event = line.slice(7);
      else if (line.startsWith('data: ')) data = JSON.parse(line.slice(6));
    }
    return { event, data };
  }

  async #ask(question) {
    if (!question) return;
    const answerEl = this.#shadow.querySelector('.xd-ask-answer');
    const citesEl = this.#shadow.querySelector('.xd-ask-cites');
    const fbEl = this.#shadow.querySelector('.xd-ask-fb');
    answerEl.textContent = '';
    citesEl.replaceChildren();
    fbEl.hidden = true;
    this.#answerId = null;
    try {
      const token = await this.#token();
      const resp = await fetch(`${this.baseUrl}/api/v1/llm/ask`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, scope: this.#askScope(), locale: this.locale }),
      });
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const { event, data } = this.#parseSseBlock(buf.slice(0, i));
          buf = buf.slice(i + 2);
          if (event === 'token') answerEl.textContent += data.text;
          else if (event === 'citations') this.#renderCitations(citesEl, data.items);
          else if (event === 'done') {
            this.#answerId = data.answer_id;
            fbEl.hidden = false;
          }
        }
      }
    } catch (err) {
      answerEl.textContent = `Error: ${err.message}`;
    }
  }

  #renderCitations(container, items) {
    container.replaceChildren();
    if (!items?.length) return;
    const label = document.createElement('div');
    label.className = 'xd-cite-label';
    label.textContent = t(this.locale, 'sources');
    container.appendChild(label);
    items.forEach((c, idx) => {
      const btn = document.createElement('button');
      btn.className = 'xd-cite';
      btn.textContent = `[${idx + 1}] ${c.title}`;
      btn.addEventListener('click', () => {
        this.#shadow.querySelector('.xd-ask').dataset.open = 'false';
        this.#loadPage(c.page_id, c.anchor);
      });
      container.appendChild(btn);
    });
  }

  async #sendFeedback(rating) {
    if (!this.#answerId) return;
    try {
      const token = await this.#token();
      await fetch(`${this.baseUrl}/api/v1/llm/feedback`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer_id: this.#answerId, rating }),
      });
      this.#shadow.querySelector('.xd-ask-fb').textContent = 'Thanks for the feedback!';
    } catch {
      /* ignore */
    }
  }

  async #summarizePage() {
    if (!this.#currentPageId) return;
    const answerEl = this.#shadow.querySelector('.xd-ask-answer');
    answerEl.textContent = 'Summarizing…';
    try {
      const token = await this.#token();
      const resp = await fetch(`${this.baseUrl}/api/v1/llm/summarize`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: { type: 'page', id: this.#currentPageId } }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const body = await resp.json();
      answerEl.textContent = body.markdown;
      const dl = document.createElement('a');
      const blob = new Blob([body.markdown], { type: 'text/markdown' });
      dl.href = URL.createObjectURL(blob);
      dl.download = 'summary.md';
      dl.textContent = 'Download .md';
      dl.className = 'xd-dl';
      const pdfBtn = document.createElement('button');
      pdfBtn.className = 'xd-dl';
      pdfBtn.textContent = 'Download PDF';
      pdfBtn.addEventListener('click', () => {
        this.#downloadExport({ type: 'artifact', id: body.artifact_id }, 'summary.pdf').catch(
          () => {}
        );
      });
      this.#shadow.querySelector('.xd-ask-cites').replaceChildren(dl, pdfBtn);
    } catch (err) {
      answerEl.textContent = `Error: ${err.message}`;
    }
  }

  #hideResults() {
    const panel = this.#shadow.querySelector('.xd-results');
    if (panel) panel.hidden = true;
  }

  #applyI18n() {
    const loc = this.locale;
    const set = (sel, key, attr) => {
      const el = this.#shadow.querySelector(sel);
      if (!el) return;
      if (attr) el.setAttribute(attr, t(loc, key));
      else el.textContent = t(loc, key);
    };
    set('.xd-search', 'search', 'placeholder');
    set('.xd-ask-btn', 'ask');
    set('.xd-export-btn', 'exportPdf');
    set('.xd-edit-btn', 'edit');
    set('.xd-ask-head strong', 'askTitle');
    set('.xd-ask-summary', 'summarize');
    const scopeOpts = this.#shadow.querySelectorAll('.xd-scope option, .xd-ask-scope option');
    scopeOpts.forEach((o) => {
      o.textContent = t(loc, o.value === 'corpus' ? 'everything' : 'thisSpace');
    });
    const send = this.#shadow.querySelector('.xd-ask-form button');
    if (send) send.textContent = t(loc, 'send');
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
      empty.textContent = t(this.locale, 'noResults');
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
      const me = await this.#api('/me'); // verify auth before loading content
      this.#applyPermissions(me);
      await this.#loadVersions();
      await this.#loadTree();
    } catch (err) {
      this.#status(`Connection failed: ${err.message}`);
      this.#emit('xdocs:error', { code: 'load_failed', message: err.message });
    }
  }

  /** Show the Edit affordance only when the principal can author this space. */
  #applyPermissions(me) {
    const writable = new Set(['write', 'admin']);
    const space = me?.space_permissions?.[this.space];
    this.#canEdit = writable.has(space) || writable.has(me?.global_permission);
    const btn = this.#shadow.querySelector('.xd-edit-btn');
    if (btn) btn.hidden = !this.#canEdit;
  }

  async #loadVersions() {
    try {
      const data = await this.#api('/spaces');
      const space = (data.items || []).find((s) => s.slug === this.space);
      const sel = this.#shadow.querySelector('.xd-version');
      sel.replaceChildren();
      const versions = space?.visible_versions || [];
      for (const v of versions) {
        const opt = document.createElement('option');
        opt.value = v.label;
        opt.textContent = v.label;
        sel.appendChild(opt);
      }
      this.#version = space?.default_version?.label || versions[0]?.label || null;
      if (this.#version) sel.value = this.#version;
      sel.hidden = versions.length < 2; // only show when there's a choice
    } catch {
      /* versions optional */
    }
  }

  async #loadTree() {
    const vq = this.#version ? `&version=${encodeURIComponent(this.#version)}` : '';
    this.#tree = await this.#api(`/spaces/${this.space}/tree?locale=${this.locale}${vq}`);
    this.#populateLanguages(this.#tree.locales || []);
    this.#renderNav();
    const first = this.#firstPage();
    if (first) this.#loadPage(first.id);
    else this.#status('No pages in this space yet.');
  }

  #populateLanguages(locales) {
    const sel = this.#shadow.querySelector('.xd-lang');
    sel.replaceChildren();
    for (const loc of locales) {
      const opt = document.createElement('option');
      opt.value = loc;
      opt.textContent = loc.toUpperCase();
      sel.appendChild(opt);
    }
    if (locales.includes(this.locale)) sel.value = this.locale;
    sel.hidden = locales.length < 2;
  }

  #firstPage() {
    for (const book of this.#tree.books) {
      for (const sec of book.sections || []) {
        if (sec.pages.length) return sec.pages[0];
      }
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
    const renderSections = (sections) =>
      (sections || [])
        .map(
          (s) => `
        <div class="xd-section-nav">${s.title}</div>
        <ul>${renderPages(s.pages)}</ul>`
        )
        .join('');
    nav.innerHTML = this.#tree.books
      .map(
        (b) => `
        <div class="xd-book">${b.title}</div>
        ${renderSections(b.sections)}
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
      this.#recordView(pageId); // analytics (H1), fire-and-forget
    } catch (err) {
      this.#status(`Failed to load page: ${err.message}`);
      this.#emit('xdocs:error', { code: 'page_failed', message: err.message });
    }
  }

  #highlightNav(pageId) {
    this.#shadow.querySelectorAll('.xd-nav button[data-page]').forEach((b) => {
      const active = b.dataset.page === pageId;
      b.classList.toggle('active', active);
      if (active) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
  }

  async #recordView(pageId) {
    try {
      const token = await this.#token();
      await fetch(`${this.baseUrl}/api/v1/analytics/pageview`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ page_id: pageId }),
      });
    } catch {
      /* analytics is best-effort */
    }
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
