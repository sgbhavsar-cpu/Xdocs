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
  #editLocale = 'en';

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
  get locales() {
    return (this.getAttribute('locales') || 'en,fr,de').split(',').map((s) => s.trim());
  }

  connectedCallback() {
    this.#editLocale = this.locale;
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
            <select class="xd-admin-lang" aria-label="Edit language"></select>
            <button class="xd-save">Save draft</button>
            <button class="xd-publish primary">Publish</button>
            <button class="xd-draft" title="LLM-assisted translation">Draft (LLM)</button>
            <button class="xd-approve">Approve</button>
            <span class="xd-admin-status"></span>
          </div>
          <div class="xd-md-toolbar">
            <button data-md="bold" title="Bold"><b>B</b></button>
            <button data-md="italic" title="Italic"><i>I</i></button>
            <button data-md="h2" title="Heading">H2</button>
            <button data-md="link" title="Link">🔗</button>
            <button data-md="code" title="Code">&lt;/&gt;</button>
            <button data-md="list" title="List">• List</button>
            <button class="xd-img" title="Insert image">🖼 Image</button>
            <input type="file" class="xd-file" accept="image/*" hidden />
          </div>
          <textarea class="xd-editor" aria-label="Markdown" placeholder="Select a page to edit…"></textarea>
          <div class="xd-revs"></div>
        </div>
        <div class="xd-preview xd-content"><p style="color:var(--xdocs-color-muted)">Preview</p></div>
      </div>`;

    const editor = this.#shadow.querySelector('.xd-editor');
    let timer = null;
    const schedulePreview = () => {
      clearTimeout(timer);
      timer = setTimeout(() => this.#preview(editor.value), 250);
    };
    editor.addEventListener('input', schedulePreview);
    // Tab inserts two spaces instead of moving focus.
    editor.addEventListener('keydown', (e) => {
      if (e.key === 'Tab') {
        e.preventDefault();
        this.#insertText('  ');
      }
    });

    // Markdown toolbar.
    this.#shadow.querySelectorAll('.xd-md-toolbar button[data-md]').forEach((b) => {
      b.addEventListener('click', () => {
        this.#mdAction(b.dataset.md);
        schedulePreview();
      });
    });
    const fileInput = this.#shadow.querySelector('.xd-file');
    this.#shadow.querySelector('.xd-img').addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      if (fileInput.files[0]) this.#uploadImage(fileInput.files[0]).then(schedulePreview);
    });
    this.#shadow.querySelector('.xd-save').addEventListener('click', () => this.#save());
    this.#shadow.querySelector('.xd-publish').addEventListener('click', () => this.#publish());
    this.#shadow.querySelector('.xd-draft').addEventListener('click', () => this.#generateDraft());
    this.#shadow.querySelector('.xd-approve').addEventListener('click', () => this.#approve());

    const lang = this.#shadow.querySelector('.xd-admin-lang');
    for (const loc of this.locales) {
      const opt = document.createElement('option');
      opt.value = loc;
      opt.textContent = loc.toUpperCase();
      lang.appendChild(opt);
    }
    lang.value = this.#editLocale;
    lang.addEventListener('change', () => {
      this.#editLocale = lang.value;
      if (this.#pageId) this.#openPage(this.#pageId);
    });
  }

  #status(msg) {
    const el = this.#shadow.querySelector('.xd-admin-status');
    if (el) el.textContent = msg;
  }

  // ---- Editor helpers ----

  #insertText(text) {
    const ed = this.#shadow.querySelector('.xd-editor');
    const { selectionStart: s, selectionEnd: e, value } = ed;
    ed.value = value.slice(0, s) + text + value.slice(e);
    ed.selectionStart = ed.selectionEnd = s + text.length;
    ed.focus();
  }

  #wrapSelection(before, after = before) {
    const ed = this.#shadow.querySelector('.xd-editor');
    const { selectionStart: s, selectionEnd: e, value } = ed;
    const sel = value.slice(s, e) || 'text';
    ed.value = value.slice(0, s) + before + sel + after + value.slice(e);
    ed.selectionStart = s + before.length;
    ed.selectionEnd = s + before.length + sel.length;
    ed.focus();
  }

  #mdAction(kind) {
    if (kind === 'bold') this.#wrapSelection('**');
    else if (kind === 'italic') this.#wrapSelection('_');
    else if (kind === 'code') this.#wrapSelection('`');
    else if (kind === 'h2') this.#insertText('\n## ');
    else if (kind === 'link') this.#wrapSelection('[', '](https://)');
    else if (kind === 'list') this.#insertText('\n- ');
  }

  async #uploadImage(file) {
    try {
      const token = await this.#tokenProvider();
      const form = new FormData();
      form.append('file', file);
      form.append('space', this.space);
      const resp = await fetch(`${this.baseUrl}/api/v1/media`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const { url } = await resp.json();
      this.#insertText(`![${file.name}](${this.baseUrl}${url})`);
      this.#status('image inserted');
    } catch (err) {
      this.#status(`Upload failed: ${err.message}`);
    }
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
        btn.dataset.book = book.id;
        btn.draggable = true;
        const title = document.createElement('span');
        title.textContent = p.title;
        const badge = document.createElement('span');
        badge.className = `xd-badge ${p.status}`;
        badge.textContent = p.status;
        btn.append(title, badge);
        btn.addEventListener('click', () => this.#openPage(p.id));
        this.#wireDrag(btn, nav);
        nav.appendChild(btn);
      }
    }
  }

  #wireDrag(btn, nav) {
    btn.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', btn.dataset.page);
      btn.classList.add('dragging');
    });
    btn.addEventListener('dragend', () => btn.classList.remove('dragging'));
    btn.addEventListener('dragover', (e) => e.preventDefault());
    btn.addEventListener('drop', (e) => {
      e.preventDefault();
      const draggedId = e.dataTransfer.getData('text/plain');
      const dragged = nav.querySelector(`button.page[data-page="${draggedId}"]`);
      if (!dragged || dragged === btn || dragged.dataset.book !== btn.dataset.book) return;
      nav.insertBefore(dragged, btn); // reorder in the DOM, then persist
      this.#persistOrder(btn.dataset.book, nav);
    });
  }

  async #persistOrder(bookId, nav) {
    const items = [...nav.querySelectorAll(`button.page[data-book="${bookId}"]`)].map((b, i) => ({
      id: b.dataset.page,
      sort_order: i,
    }));
    try {
      await this.#api('/admin/pages/reorder', {
        method: 'POST',
        body: JSON.stringify({ items }),
      });
      this.#status('reordered');
    } catch (err) {
      this.#status(`Reorder failed: ${err.message}`);
    }
  }

  async #openPage(pageId) {
    this.#pageId = pageId;
    this.#shadow.querySelectorAll('.xd-admin-tree button.page').forEach((b) => {
      b.classList.toggle('active', b.dataset.page === pageId);
    });
    try {
      const tr = await this.#api(`/admin/pages/${pageId}/translations/${this.#editLocale}`);
      this.#revision = tr.revision;
      this.#shadow.querySelector('.xd-title-input').value = tr.title;
      this.#shadow.querySelector('.xd-editor').value = tr.markdown;
      this.#preview(tr.markdown);
      this.#loadRevisions();
      this.#status(`rev ${tr.revision} · ${tr.status} · ${tr.translation_status}`);
    } catch (err) {
      if (err.status === 404) {
        // No translation in this locale yet — offer an LLM-assisted draft.
        this.#revision = null;
        this.#shadow.querySelector('.xd-editor').value = '';
        this.#shadow.querySelector('.xd-preview').innerHTML = '';
        this.#status(`No “${this.#editLocale}” translation — use Draft (LLM)`);
      } else {
        this.#status(`Error: ${err.message}`);
      }
    }
  }

  async #generateDraft() {
    if (!this.#pageId) return;
    this.#status('Generating draft…');
    try {
      await this.#api(`/admin/pages/${this.#pageId}/translations/${this.#editLocale}/draft`, {
        method: 'POST',
        body: JSON.stringify({ source_locale: this.locale }),
      });
      await this.#openPage(this.#pageId);
      this.#status(`draft generated (${this.#editLocale})`);
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #approve() {
    if (!this.#pageId) return;
    try {
      const res = await this.#api(
        `/admin/pages/${this.#pageId}/translations/${this.#editLocale}/approve`,
        { method: 'POST' }
      );
      this.#status(`status: ${res.translation_status}`);
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
      const res = await this.#api(`/admin/pages/${this.#pageId}/translations/${this.#editLocale}`, {
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
        `/admin/pages/${this.#pageId}/revisions?locale=${this.#editLocale}`
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
        `/admin/pages/${this.#pageId}/revisions/${revision}/restore?locale=${this.#editLocale}`,
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
