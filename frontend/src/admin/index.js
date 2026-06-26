/**
 * <xdocs-admin> — the CMS authoring app (F1).
 *
 * Tree of books/pages (drafts included), a markdown editor with server-rendered
 * live preview (parity with the reader), draft save with optimistic locking,
 * publish, revision history + restore, and media upload/insert. Heavier than the
 * reader by design (editing surface), but still framework-free.
 */

// Replaced at build time with the compiled Tailwind stylesheet (build.mjs).
const STYLES = __XDOCS_CSS__;

const slugify = (s) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '') || 'page';

class XdocsAdmin extends HTMLElement {
  static get observedAttributes() {
    return ['base-url', 'space', 'locale', 'theme'];
  }

  #shadow;
  #tokenProvider = null;
  #ready = false;
  #pageId = null;
  #revision = null;

  constructor() {
    super();
    this.#shadow = this.attachShadow({ mode: 'open' });
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(STYLES);
    this.#shadow.adoptedStyleSheets = [sheet];
  }

  set tokenProvider(fn) {
    this.#tokenProvider = fn;
    if (this.#ready) this.#loadTree();
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
    this.#upgradeProperty('tokenProvider');
    this.#ready = true;
    this.dispatchEvent(new CustomEvent('xdocs:ready', { bubbles: true, composed: true }));
    this.#loadTree();
  }

  attributeChangedCallback(name) {
    if (!this.#ready) return;
    if (name === 'theme') this.#applyTheme();
    else this.#loadTree();
  }

  #upgradeProperty(prop) {
    if (Object.prototype.hasOwnProperty.call(this, prop)) {
      const v = this[prop];
      delete this[prop];
      this[prop] = v;
    }
  }

  #applyTheme() {
    const theme = this.getAttribute('theme') || 'auto';
    const dark =
      theme === 'dark' ||
      (theme === 'auto' && window.matchMedia?.('(prefers-color-scheme: dark)').matches);
    this.setAttribute('data-theme', dark ? 'dark' : 'light');
  }

  async #api(path, opts = {}) {
    const token = await this.#tokenProvider();
    const resp = await fetch(`${this.baseUrl}/api/v1${path}`, {
      ...opts,
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        ...(opts.headers || {}),
      },
    });
    if (!resp.ok) {
      const err = new Error(`HTTP ${resp.status}`);
      err.status = resp.status;
      throw err;
    }
    return resp.status === 204 ? null : resp.json();
  }

  #renderShell() {
    this.#shadow.innerHTML = `
      <div class="xd-admin">
        <nav class="xd-admin-tree" aria-label="Pages"><p>Loading…</p></nav>
        <div class="xd-admin-main">
          <div class="xd-admin-bar">
            <input class="xd-title-input" aria-label="Page title" placeholder="Page title" />
            <button class="xd-save">Save draft</button>
            <button class="xd-publish primary">Publish</button>
            <span class="xd-admin-status"></span>
          </div>
          <textarea class="xd-editor" aria-label="Markdown" placeholder="Select a page to edit…"></textarea>
          <div class="xd-revs"></div>
        </div>
        <div class="xd-preview xd-content"><p style="color:var(--xdocs-color-muted)">Preview</p></div>
      </div>`;

    const editor = this.#shadow.querySelector('.xd-editor');
    let timer = null;
    editor.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => this.#preview(editor.value), 250);
    });
    this.#shadow.querySelector('.xd-save').addEventListener('click', () => this.#save());
    this.#shadow.querySelector('.xd-publish').addEventListener('click', () => this.#publish());
  }

  #status(msg) {
    const el = this.#shadow.querySelector('.xd-admin-status');
    if (el) el.textContent = msg;
  }

  async #loadTree() {
    if (!this.baseUrl || !this.#tokenProvider || !this.space) return;
    try {
      const tree = await this.#api(`/admin/spaces/${this.space}/tree`);
      this.#renderTree(tree);
    } catch (err) {
      this.#shadow.querySelector('.xd-admin-tree').textContent = `Error: ${err.message}`;
    }
  }

  #renderTree(tree) {
    const nav = this.#shadow.querySelector('.xd-admin-tree');
    nav.replaceChildren();
    for (const book of tree.books) {
      const head = document.createElement('div');
      head.className = 'xd-admin-book';
      head.textContent = book.title;
      const add = document.createElement('button');
      add.className = 'xd-newpage';
      add.textContent = '+ Page';
      add.addEventListener('click', () => this.#newPage(book.id));
      head.appendChild(add);
      nav.appendChild(head);
      for (const p of book.pages) {
        const btn = document.createElement('button');
        btn.className = 'page';
        btn.dataset.page = p.id;
        const title = document.createElement('span');
        title.textContent = p.title;
        const badge = document.createElement('span');
        badge.className = `xd-badge ${p.status}`;
        badge.textContent = p.status;
        btn.append(title, badge);
        btn.addEventListener('click', () => this.#openPage(p.id));
        nav.appendChild(btn);
      }
    }
  }

  async #openPage(pageId) {
    try {
      const tr = await this.#api(`/admin/pages/${pageId}/translations/${this.locale}`);
      this.#pageId = pageId;
      this.#revision = tr.revision;
      this.#shadow.querySelector('.xd-title-input').value = tr.title;
      this.#shadow.querySelector('.xd-editor').value = tr.markdown;
      this.#preview(tr.markdown);
      this.#loadRevisions();
      this.#status(`rev ${tr.revision} · ${tr.status}`);
      this.#shadow.querySelectorAll('.xd-admin-tree button.page').forEach((b) => {
        b.classList.toggle('active', b.dataset.page === pageId);
      });
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #preview(markdown) {
    try {
      const { html } = await this.#api('/admin/preview', {
        method: 'POST',
        body: JSON.stringify({ markdown }),
      });
      this.#shadow.querySelector('.xd-preview').innerHTML = html; // server-sanitized
    } catch {
      /* ignore preview errors */
    }
  }

  async #save() {
    if (!this.#pageId) return;
    const markdown = this.#shadow.querySelector('.xd-editor').value;
    const title = this.#shadow.querySelector('.xd-title-input').value;
    try {
      const res = await this.#api(`/admin/pages/${this.#pageId}/translations/${this.locale}`, {
        method: 'PUT',
        body: JSON.stringify({ markdown, title, base_revision: this.#revision }),
      });
      this.#revision = res.revision;
      this.#status(`saved · rev ${res.revision}`);
      this.#loadRevisions();
    } catch (err) {
      this.#status(err.status === 409 ? 'Conflict: reload the page' : `Error: ${err.message}`);
    }
  }

  async #publish() {
    if (!this.#pageId) return;
    try {
      await this.#api(`/admin/pages/${this.#pageId}/publish`, { method: 'POST' });
      this.#status('published');
      this.#loadTree();
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #loadRevisions() {
    if (!this.#pageId) return;
    const box = this.#shadow.querySelector('.xd-revs');
    try {
      const { items } = await this.#api(
        `/admin/pages/${this.#pageId}/revisions?locale=${this.locale}`
      );
      box.replaceChildren();
      const label = document.createElement('strong');
      label.textContent = 'Revisions';
      box.appendChild(label);
      for (const r of items) {
        const row = document.createElement('div');
        const restore = document.createElement('button');
        restore.textContent = `rev ${r.revision} · restore`;
        restore.addEventListener('click', () => this.#restore(r.revision));
        row.appendChild(restore);
        box.appendChild(row);
      }
    } catch {
      /* ignore */
    }
  }

  async #restore(revision) {
    try {
      const res = await this.#api(
        `/admin/pages/${this.#pageId}/revisions/${revision}/restore?locale=${this.locale}`,
        { method: 'POST' }
      );
      this.#revision = res.revision;
      await this.#openPage(this.#pageId);
      this.#status(`restored rev ${revision}`);
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #newPage(bookId) {
    const title = window.prompt?.('New page title');
    if (!title) return;
    try {
      const page = await this.#api('/admin/pages', {
        method: 'POST',
        body: JSON.stringify({
          book_id: bookId,
          slug: slugify(title),
          title,
          markdown: `# ${title}\n\n`,
        }),
      });
      await this.#loadTree();
      this.#openPage(page.id);
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }
}

if (!customElements.get('xdocs-admin')) {
  customElements.define('xdocs-admin', XdocsAdmin);
}

export { XdocsAdmin };
