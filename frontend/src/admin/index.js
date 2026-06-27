/**
 * <xdocs-admin> — the CMS authoring app (F1).
 *
 * A framework-free rich Markdown editor: a tree of books/pages (drafts included),
 * a formatting toolbar with keyboard shortcuts, smart list continuation, image
 * paste/drop upload, a live server-rendered preview (parity with the reader),
 * split / write / preview / zen view modes, a word-count & status bar, draft save
 * with optimistic locking, publish / unpublish, page delete, revision history with
 * preview + restore, LLM-assisted translation, and PDF import.
 */

import { htmlToMarkdown } from '../shared/html-md.js';

// Replaced at build time with the compiled Tailwind stylesheet (build.mjs).
const STYLES = __XDOCS_CSS__;

const slugify = (s) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '') || 'page';

const TABLE_TEMPLATE = '| Column A | Column B |\n| --- | --- |\n| cell | cell |';

// Insert commands offered by the slash (`/`) menu. `key` maps to an action in
// #runSlash; `label`/`icon` are display only and `key` is also matched while filtering.
const SLASH_ITEMS = [
  { key: 'h1', label: 'Heading 1', icon: 'H1' },
  { key: 'h2', label: 'Heading 2', icon: 'H2' },
  { key: 'h3', label: 'Heading 3', icon: 'H3' },
  { key: 'ul', label: 'Bullet list', icon: '•' },
  { key: 'ol', label: 'Numbered list', icon: '1.' },
  { key: 'task', label: 'Task list', icon: '☑' },
  { key: 'quote', label: 'Quote', icon: '❝' },
  { key: 'code', label: 'Code block', icon: '{ }' },
  { key: 'table', label: 'Table', icon: '▦' },
  { key: 'hr', label: 'Divider', icon: '―' },
  { key: 'mermaid', label: 'Diagram (Mermaid)', icon: '📈' },
  { key: 'math', label: 'Math (KaTeX)', icon: '∑' },
  { key: 'link', label: 'Link', icon: '🔗' },
];

// Quick-insert glyphs for the emoji / special-character picker.
const EMOJI_CHARS = [
  '😀', '😉', '😅', '😍', '🤔', '👍', '👎', '🙏', '🎉', '🔥',
  '⭐', '✅', '❌', '⚠️', '💡', '📌', '📎', '🔗', '➡️', '⬅️',
  '•', '–', '—', '…', '©', '®', '™', '°', '±', '×',
  '÷', '≈', '≤', '≥', '→', '←', '↔', '∞', '∑', '√', 'π', 'µ',
];

class XdocsAdmin extends HTMLElement {
  static get observedAttributes() {
    return ['base-url', 'space', 'locale', 'theme'];
  }

  // Preset accent colours offered in the space form.
  static #PALETTE = ['#0b5cad', '#16a34a', '#9333ea', '#dc2626', '#ea580c', '#0891b2', '#475569'];

  #shadow;
  #tokenProvider = null;
  #ready = false;
  #mode = 'editor'; // 'spaces' | 'books' | 'editor'
  #spaces = [];
  #spaceMeta = null; // { title, color } for the open space
  #editingSpace = null; // slug being edited in the form, or null when creating
  #books = []; // books in the open space (from the tree)
  #bookId = null; // the book currently open in the editor
  #pageId = null;
  #pageVariant = 'single'; // 'single' | 'draft' | 'published' (read-only)
  #hasDraft = false;
  #revision = null;
  #editLocale = 'en';
  #pendingPageId = null;
  #pageStatus = null;
  #translationStatus = null;
  #dirty = false;
  #previewTimer = null;
  #outlineTimer = null;
  #previewBlocks = []; // cached [data-sl] elements of the live preview (sync)
  #syncOn = true; // editor ↔ preview selection + scroll sync enabled
  #syncGuard = false; // re-entrancy guard for two-way scroll sync
  #findMatches = []; // [start,end] offsets of the current Find query
  #findIdx = -1; // index of the active match within #findMatches
  #slashStart = -1; // offset of the '/' that opened the slash menu (-1 = closed)
  #slashActive = 0; // highlighted item index in the slash menu
  #beforeUnload = (e) => {
    e.preventDefault();
    e.returnValue = '';
  };

  constructor() {
    super();
    this.#shadow = this.attachShadow({ mode: 'open' });
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(STYLES);
    this.#shadow.adoptedStyleSheets = [sheet];
  }

  set tokenProvider(fn) {
    this.#tokenProvider = fn;
    if (this.#ready) this.#refresh();
  }
  get tokenProvider() {
    return this.#tokenProvider;
  }

  /** Open a specific page once the tree has loaded (used when arriving from the
   *  reader's Edit button so the author lands on the page they were reading).
   *  This is a deep-link: jump straight into the editor for that page's book,
   *  bypassing the spaces/books screens. */
  set openPageId(id) {
    this.#pendingPageId = id || null;
    if (this.#ready && this.#pendingPageId && this.space) {
      this.#mode = 'editor';
      this.#bookId = null; // resolved from the pending page in #loadTree
      this.#applyMode();
      this.#loadTree();
    } else {
      this.#tryOpenPending();
    }
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
    this.#boot();
  }

  disconnectedCallback() {
    window.removeEventListener('beforeunload', this.#beforeUnload);
  }

  attributeChangedCallback(name) {
    if (!this.#ready) return;
    if (name === 'theme') this.#applyTheme();
    else if (name === 'space') this.#boot();
    else this.#refresh();
  }

  /** Pick the screen (spaces / books / editor) from the `space` attribute and load it. */
  #boot() {
    if (!this.space) this.#mode = 'spaces';
    else if (this.#pendingPageId) this.#mode = 'editor'; // reader → edit deep-link
    else this.#mode = 'books';
    this.#applyMode();
    this.#refresh();
  }

  #refresh() {
    if (!this.#ready) return;
    if (this.#mode === 'spaces') this.#loadSpaces();
    else if (this.#mode === 'books') this.#loadBooks();
    else this.#loadTree();
  }

  #applyMode() {
    const root = this.#el('.xd-admin-root');
    if (root) root.dataset.mode = this.#mode;
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

  // ---- Shell ----

  #renderShell() {
    this.#shadow.innerHTML = `
      <div class="xd-admin-root" data-mode="editor">
      <section class="xd-spaces" aria-label="Spaces">
        <div class="xd-spaces-head">
          <strong>Spaces</strong>
          <span class="xd-bar-spacer"></span>
          <button class="xd-new-space primary">＋ New space</button>
        </div>
        <form class="xd-space-form" hidden>
          <div class="xd-form-row">
            <label>Title<input class="xd-sf-title" required placeholder="My Space" /></label>
            <label>Slug<input class="xd-sf-slug" placeholder="my-space" /></label>
          </div>
          <label>Description<input class="xd-sf-desc" placeholder="Short description" /></label>
          <div class="xd-form-row">
            <label>Default locale<input class="xd-sf-locale" value="en" /></label>
            <label class="xd-sf-color-wrap">Color
              <span class="xd-sf-swatches"></span>
              <input type="color" class="xd-sf-color" value="#0b5cad" />
            </label>
          </div>
          <div class="xd-form-actions">
            <span class="xd-sf-status" aria-live="polite"></span>
            <span class="xd-bar-spacer"></span>
            <button type="button" class="xd-sf-cancel">Cancel</button>
            <button type="submit" class="xd-sf-save primary">Save</button>
          </div>
        </form>
        <div class="xd-space-grid"><p class="xd-muted">Loading…</p></div>
      </section>
      <section class="xd-books" aria-label="Books">
        <div class="xd-books-head">
          <button class="xd-books-back" title="Back to spaces">⊞ Spaces</button>
          <strong class="xd-books-title">Books</strong>
          <span class="xd-bar-spacer"></span>
          <button class="xd-new-book primary">＋ Add book</button>
          <button class="xd-import-book" title="Create a book from a PDF">⤒ Import PDF</button>
        </div>
        <div class="xd-book-grid"><p class="xd-muted">Loading…</p></div>
      </section>
      <div class="xd-admin" data-view="split" data-zen="false">
        <nav class="xd-admin-tree" aria-label="Pages"><p>Loading…</p></nav>
        <div class="xd-splitter" role="separator" aria-label="Resize sidebar"></div>
        <div class="xd-admin-main">
          <div class="xd-admin-bar">
            <button class="xd-spaces-btn" aria-label="Back to books" title="Back to books">← Books</button>
            <button class="xd-view-btn" aria-label="Back to reading" title="Back to reading">← Reading</button>
            <input class="xd-title-input" aria-label="Page title" placeholder="Page title" />
            <select class="xd-admin-lang" aria-label="Edit language"></select>
            <span class="xd-status-badge" data-s=""></span>
            <span class="xd-admin-status" aria-live="polite"></span>
            <span class="xd-bar-spacer"></span>
            <div class="xd-viewmodes" role="group" aria-label="View mode">
              <button data-vm="write" title="Editor only">✎</button>
              <button data-vm="split" class="active" title="Split view">▣</button>
              <button data-vm="preview" title="Preview only">👁</button>
            </div>
            <button class="xd-sync active" title="Sync editor ↔ preview selection &amp; scroll" aria-pressed="true">🔗</button>
            <button class="xd-zen" title="Fullscreen (Esc to exit)" aria-label="Fullscreen">⤢</button>
            <button class="xd-outline-btn" title="Document outline" aria-label="Outline">☰</button>
            <button class="xd-history" title="Revision history" aria-label="History">⟲</button>
            <button class="xd-save">Save draft</button>
            <button class="xd-publish primary">Publish</button>
            <span class="xd-menu-wrap">
              <button class="xd-more" title="More actions" aria-haspopup="true">⋯</button>
              <div class="xd-menu" hidden role="menu">
                <button class="xd-draft" role="menuitem" title="LLM-assisted translation">🌐 Translate draft (LLM)</button>
                <button class="xd-approve" role="menuitem">✓ Approve translation</button>
                <button class="xd-discard" role="menuitem" title="Revert edits to the published version">↩ Discard draft</button>
                <button class="xd-unpublish" role="menuitem">⤓ Unpublish</button>
                <button class="xd-delete danger" role="menuitem">🗑 Delete page</button>
              </div>
            </span>
          </div>
          <div class="xd-md-toolbar">
            <select class="xd-block" aria-label="Block format" title="Paragraph style">
              <option value="p">Paragraph</option>
              <option value="1">Heading 1</option>
              <option value="2">Heading 2</option>
              <option value="3">Heading 3</option>
              <option value="4">Heading 4</option>
              <option value="5">Heading 5</option>
              <option value="6">Heading 6</option>
              <option value="quote">Quote</option>
              <option value="code">Code block</option>
            </select>
            <span class="xd-tb-sep"></span>
            <button data-md="bold" title="Bold (Ctrl+B)"><b>B</b></button>
            <button data-md="italic" title="Italic (Ctrl+I)"><i>I</i></button>
            <button data-md="strike" title="Strikethrough"><s>S</s></button>
            <button data-md="code" title="Inline code">&lt;/&gt;</button>
            <span class="xd-tb-sep"></span>
            <button data-md="link" title="Link (Ctrl+K)">🔗</button>
            <button class="xd-img" title="Insert image (or paste / drop)">🖼</button>
            <button class="xd-img-opts" title="Resize / position the image at the cursor">↔ Img</button>
            <button class="xd-import-pdf" title="Import a PDF's text &amp; images into this page">⤒ PDF</button>
            <span class="xd-tb-sep"></span>
            <button data-md="ul" title="Bullet list">• List</button>
            <button data-md="ol" title="Numbered list">1.</button>
            <button data-md="task" title="Task list">☑</button>
            <button data-md="quote" title="Quote">❝</button>
            <span class="xd-tb-sep"></span>
            <select class="xd-code-lang" aria-label="Code language" title="Code block language">
              <option value="">plain</option>
              <option value="bash">bash</option>
              <option value="json">json</option>
              <option value="yaml">yaml</option>
              <option value="sql">sql</option>
              <option value="javascript">javascript</option>
              <option value="typescript">typescript</option>
              <option value="python">python</option>
              <option value="html">html</option>
              <option value="css">css</option>
              <option value="java">java</option>
              <option value="csharp">csharp</option>
              <option value="go">go</option>
              <option value="rust">rust</option>
              <option value="c">c</option>
              <option value="cpp">cpp</option>
              <option value="php">php</option>
              <option value="ruby">ruby</option>
              <option value="markdown">markdown</option>
            </select>
            <button data-md="codeblock" title="Code block (uses selected language)">{ }</button>
            <button data-md="table" title="Table">▦</button>
            <button data-tbl="row" title="Insert table row below the caret">＋Row</button>
            <button data-tbl="col" title="Insert table column right of the caret">＋Col</button>
            <button data-tbl="delrow" title="Delete the table row at the caret">－Row</button>
            <button data-tbl="delcol" title="Delete the table column at the caret">－Col</button>
            <button data-md="hr" title="Divider">―</button>
            <button data-md="mermaid" title="Diagram (Mermaid)">📈</button>
            <button data-md="math" title="Math (KaTeX)">∑</button>
            <span class="xd-tb-sep"></span>
            <button class="xd-emoji-btn" title="Emoji &amp; symbols">😀</button>
            <button class="xd-find-btn" title="Find &amp; replace (Ctrl+F)">🔍</button>
            <button class="xd-spell" title="Toggle spell check" aria-pressed="false">📝</button>
            <input type="file" class="xd-file" accept="image/*" hidden />
            <input type="file" class="xd-pdf-file" accept="application/pdf,.pdf" hidden />
          </div>
          <div class="xd-find" hidden>
            <input class="xd-find-input" aria-label="Find" placeholder="Find" />
            <button class="xd-find-case" title="Match case" aria-pressed="false">Aa</button>
            <button class="xd-find-re" title="Regular expression" aria-pressed="false">.*</button>
            <span class="xd-find-count">0/0</span>
            <button class="xd-find-prev" title="Previous (Shift+Enter)">▲</button>
            <button class="xd-find-next" title="Next (Enter)">▼</button>
            <input class="xd-replace-input" aria-label="Replace with" placeholder="Replace" />
            <button class="xd-replace-one" title="Replace">Replace</button>
            <button class="xd-replace-all" title="Replace all">All</button>
            <span class="xd-bar-spacer"></span>
            <button class="xd-find-close" aria-label="Close find">✕</button>
          </div>
          <div class="xd-edit-wrap">
            <textarea class="xd-editor" aria-label="Markdown" placeholder="Select a page to edit…"></textarea>
            <div class="xd-preview xd-content"><p class="xd-muted">Preview</p></div>
          </div>
          <div class="xd-statusbar">
            <span class="xd-counts">—</span>
            <span class="xd-tb-sep"></span>
            <span class="xd-cursor">Ln 1, Col 1</span>
            <span class="xd-tb-sep"></span>
            <span class="xd-sel-count"></span>
            <span class="xd-bar-spacer"></span>
            <span class="xd-saved"></span>
          </div>
        </div>
        <aside class="xd-revs-panel" hidden aria-label="Revision history">
          <div class="xd-revs-head"><strong>History</strong><button class="xd-revs-close" aria-label="Close">✕</button></div>
          <div class="xd-revs"></div>
        </aside>
        <aside class="xd-outline-panel" hidden aria-label="Document outline">
          <div class="xd-revs-head"><strong>Outline</strong><button class="xd-outline-close" aria-label="Close">✕</button></div>
          <div class="xd-outline"></div>
        </aside>
        <div class="xd-slash" hidden role="listbox" aria-label="Insert"></div>
        <div class="xd-emoji" hidden role="menu" aria-label="Emoji and symbols"></div>
      </div>
      </div>`;

    this.#wireEditor();
    this.#wireToolbar();
    this.#wireBar();
    this.#wireLang();
    this.#wireSpaces();
    this.#wireBooks();
    this.#wireSplitter();
    this.#wireEditorPlus();
  }

  /** Drag the splitter to resize the tree; width persists across sessions. */
  #wireSplitter() {
    const admin = this.#el('.xd-admin');
    const splitter = this.#el('.xd-splitter');
    const saved = (() => {
      try {
        return localStorage.getItem('xdocs-tree-w');
      } catch {
        return null;
      }
    })();
    if (saved) admin.style.setProperty('--xd-tree-w', saved);

    const clamp = (px) => Math.max(160, Math.min(520, px));
    const onMove = (e) => {
      const rect = admin.getBoundingClientRect();
      const w = clamp(e.clientX - rect.left);
      admin.style.setProperty('--xd-tree-w', `${w}px`);
    };
    const onUp = () => {
      splitter.classList.remove('dragging');
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      try {
        localStorage.setItem('xdocs-tree-w', admin.style.getPropertyValue('--xd-tree-w'));
      } catch {
        /* ignore storage failures */
      }
    };
    splitter.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      splitter.classList.add('dragging');
      document.addEventListener('pointermove', onMove);
      document.addEventListener('pointerup', onUp);
    });
  }

  #el(sel) {
    return this.#shadow.querySelector(sel);
  }
  #editor() {
    return this.#el('.xd-editor');
  }

  #wireEditor() {
    const editor = this.#editor();
    editor.addEventListener('input', () => {
      this.#setDirty(true);
      this.#updateCounts();
      this.#schedulePreview();
    });
    editor.addEventListener('keydown', (e) => this.#onEditorKey(e));
    editor.addEventListener('paste', (e) => this.#onPaste(e));
    editor.addEventListener('dragover', (e) => {
      if (e.dataTransfer?.types?.includes('Files')) e.preventDefault();
    });
    editor.addEventListener('drop', (e) => this.#onDrop(e));
  }

  #wireToolbar() {
    this.#shadow.querySelectorAll('.xd-md-toolbar button[data-md]').forEach((b) => {
      b.addEventListener('click', () => {
        this.#mdAction(b.dataset.md);
        this.#afterEdit();
      });
    });
    this.#el('.xd-block').addEventListener('change', (e) => {
      this.#setBlock(e.target.value);
      e.target.value = 'p';
      this.#afterEdit();
    });
    const fileInput = this.#el('.xd-file');
    this.#el('.xd-img').addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      if (fileInput.files[0]) this.#uploadImage(fileInput.files[0]).then(() => this.#afterEdit());
      fileInput.value = '';
    });
    // Changing the language re-tags the fenced code block the caret sits in.
    this.#el('.xd-code-lang').addEventListener('change', (e) => {
      this.#setCodeFenceLang(e.target.value);
    });
    // Resize / position the image under the caret.
    this.#el('.xd-img-opts').addEventListener('click', () => this.#imageOptions());
    // Import a PDF's text + images into the current page at the caret.
    const pdfInput = this.#el('.xd-pdf-file');
    this.#el('.xd-import-pdf').addEventListener('click', () => pdfInput.click());
    pdfInput.addEventListener('change', () => {
      if (pdfInput.files[0]) this.#importPdfIntoPage(pdfInput.files[0]);
      pdfInput.value = '';
    });
  }

  // ---- Word-like editing: find/replace, outline, line ops, slash & emoji
  //      menus, table tools, and editor ↔ preview block/line sync. ----

  #wireEditorPlus() {
    const ed = this.#editor();
    // Track the caret for the status bar and the editor→preview highlight.
    const track = () => {
      this.#updateCursor();
      this.#syncPreviewToCaret();
    };
    ed.addEventListener('keyup', track);
    ed.addEventListener('click', track);
    ed.addEventListener('input', () => {
      this.#updateCursor();
      this.#scheduleOutline();
      this.#handleSlashInput();
    });
    ed.addEventListener('scroll', () => this.#syncScroll('editor'));

    // Table column / row tools.
    this.#shadow.querySelectorAll('.xd-md-toolbar button[data-tbl]').forEach((b) => {
      b.addEventListener('click', () => {
        this.#tableOp(b.dataset.tbl);
        this.#afterEdit();
      });
    });

    // Find & replace bar.
    this.#el('.xd-find-btn').addEventListener('click', () => this.#openFind());
    this.#el('.xd-find-close').addEventListener('click', () => this.#closeFind());
    const fi = this.#el('.xd-find-input');
    fi.addEventListener('input', () => this.#findAll());
    fi.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        this.#findStep(e.shiftKey ? -1 : 1);
      } else if (e.key === 'Escape') {
        this.#closeFind();
      }
    });
    this.#el('.xd-find-next').addEventListener('click', () => this.#findStep(1));
    this.#el('.xd-find-prev').addEventListener('click', () => this.#findStep(-1));
    this.#el('.xd-replace-one').addEventListener('click', () => this.#replaceOne());
    this.#el('.xd-replace-all').addEventListener('click', () => this.#replaceAll());
    const toggleFlag = (sel) => {
      const b = this.#el(sel);
      const on = b.getAttribute('aria-pressed') !== 'true';
      b.setAttribute('aria-pressed', String(on));
      b.classList.toggle('active', on);
      this.#findAll();
    };
    this.#el('.xd-find-case').addEventListener('click', () => toggleFlag('.xd-find-case'));
    this.#el('.xd-find-re').addEventListener('click', () => toggleFlag('.xd-find-re'));

    // Outline navigator.
    this.#el('.xd-outline-btn').addEventListener('click', () => this.#toggleOutline());
    this.#el('.xd-outline-close').addEventListener('click', () => this.#toggleOutline(false));

    // Emoji / special-character picker.
    this.#buildEmoji();
    this.#el('.xd-emoji-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      const p = this.#el('.xd-emoji');
      if (p.hidden) this.#positionEmoji();
      p.hidden = !p.hidden;
    });

    // Spell-check toggle (native textarea spellcheck).
    this.#el('.xd-spell').addEventListener('click', () => {
      const on = !ed.spellcheck;
      ed.spellcheck = on;
      const b = this.#el('.xd-spell');
      b.setAttribute('aria-pressed', String(on));
      b.classList.toggle('active', on);
      ed.blur();
      ed.focus();
    });

    // Editor ↔ preview sync toggle.
    this.#el('.xd-sync').addEventListener('click', () => {
      this.#syncOn = !this.#syncOn;
      const b = this.#el('.xd-sync');
      b.classList.toggle('active', this.#syncOn);
      b.setAttribute('aria-pressed', String(this.#syncOn));
    });

    // Preview → editor: click a rendered block to select its source lines; the
    // preview also drives scroll sync.
    const preview = this.#el('.xd-preview');
    preview.addEventListener('click', (e) => this.#syncCaretFromPreview(e));
    preview.addEventListener('scroll', () => this.#syncScroll('preview'));

    // Dismiss the slash / emoji popups on an outside click.
    this.#shadow.addEventListener('click', (e) => {
      const path = e.composedPath();
      if (!path.includes(this.#el('.xd-emoji')) && !path.includes(this.#el('.xd-emoji-btn'))) {
        this.#el('.xd-emoji').hidden = true;
      }
      if (!path.includes(this.#el('.xd-slash'))) this.#hideSlash();
    });
    this.#updateCursor();
  }

  // ---- Offsets / lines ----

  #lineOfOffset(offset) {
    return this.#editor().value.slice(0, offset).split('\n').length - 1;
  }

  #offsetOfLine(line) {
    const lines = this.#editor().value.split('\n');
    let off = 0;
    for (let i = 0; i < line && i < lines.length; i += 1) off += lines[i].length + 1;
    return off;
  }

  #scrollToOffset(offset) {
    const ed = this.#editor();
    const line = this.#lineOfOffset(offset);
    const lh = parseFloat(window.getComputedStyle(ed).lineHeight) || 18;
    const target = line * lh;
    if (target < ed.scrollTop || target > ed.scrollTop + ed.clientHeight - lh) {
      ed.scrollTop = Math.max(0, target - ed.clientHeight / 2);
    }
  }

  // ---- Status bar (cursor position + selection word count) ----

  #updateCursor() {
    const ed = this.#editor();
    const upto = ed.value.slice(0, ed.selectionStart);
    const line = upto.split('\n').length;
    const col = upto.length - upto.lastIndexOf('\n');
    const cur = this.#el('.xd-cursor');
    if (cur) cur.textContent = `Ln ${line}, Col ${col}`;
    const selEl = this.#el('.xd-sel-count');
    if (selEl) {
      const sel = ed.value.slice(ed.selectionStart, ed.selectionEnd);
      const words = (sel.trim().match(/\S+/g) || []).length;
      selEl.textContent = sel ? `${words} word(s) selected` : '';
    }
  }

  // ---- Find & replace ----

  #openFind() {
    const bar = this.#el('.xd-find');
    bar.hidden = false;
    const ed = this.#editor();
    const sel = ed.value.slice(ed.selectionStart, ed.selectionEnd);
    if (sel && !sel.includes('\n')) this.#el('.xd-find-input').value = sel;
    const fi = this.#el('.xd-find-input');
    fi.focus();
    fi.select();
    this.#findAll();
  }

  #closeFind() {
    this.#el('.xd-find').hidden = true;
    this.#findMatches = [];
    this.#findIdx = -1;
    this.#editor().focus();
  }

  #findRegex() {
    const q = this.#el('.xd-find-input').value;
    if (!q) return null;
    const flags = this.#el('.xd-find-case').getAttribute('aria-pressed') === 'true' ? 'g' : 'gi';
    const isRe = this.#el('.xd-find-re').getAttribute('aria-pressed') === 'true';
    try {
      return new RegExp(isRe ? q : q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), flags);
    } catch {
      return null; // invalid user regex — treated as "no matches"
    }
  }

  #findAll() {
    const v = this.#editor().value;
    const re = this.#findRegex();
    this.#findMatches = [];
    if (re) {
      let m;
      while ((m = re.exec(v)) !== null) {
        this.#findMatches.push([m.index, m.index + m[0].length]);
        if (m[0].length === 0) re.lastIndex += 1; // guard against zero-width loops
      }
    }
    this.#findIdx = this.#findMatches.length ? 0 : -1;
    if (this.#findIdx >= 0) this.#gotoMatch(this.#findIdx);
    this.#renderFindCount();
  }

  #renderFindCount() {
    const n = this.#findMatches.length;
    this.#el('.xd-find-count').textContent = `${n ? this.#findIdx + 1 : 0}/${n}`;
  }

  #gotoMatch(i) {
    const m = this.#findMatches[i];
    if (!m) return;
    const ed = this.#editor();
    ed.setSelectionRange(m[0], m[1]);
    this.#scrollToOffset(m[0]);
    this.#renderFindCount();
    this.#updateCursor();
  }

  #findStep(dir) {
    if (!this.#findMatches.length) return;
    this.#findIdx = (this.#findIdx + dir + this.#findMatches.length) % this.#findMatches.length;
    this.#gotoMatch(this.#findIdx);
  }

  #replaceOne() {
    const m = this.#findMatches[this.#findIdx];
    if (!m) return;
    const repl = this.#el('.xd-replace-input').value;
    this.#applyEdit(m[0], m[1], repl, m[0], m[0] + repl.length);
    this.#afterEdit();
    this.#findAll();
  }

  #replaceAll() {
    if (!this.#findMatches.length) return;
    const repl = this.#el('.xd-replace-input').value;
    // Right-to-left so earlier offsets stay valid; one applyEdit per match keeps
    // each replacement on the native undo stack.
    for (let i = this.#findMatches.length - 1; i >= 0; i -= 1) {
      const [s, e] = this.#findMatches[i];
      this.#applyEdit(s, e, repl);
    }
    this.#afterEdit();
    this.#findAll();
  }

  // ---- Outline navigator ----

  #toggleOutline(force) {
    const panel = this.#el('.xd-outline-panel');
    const show = force ?? panel.hidden;
    panel.hidden = !show;
    if (show) this.#renderOutline();
  }

  #scheduleOutline() {
    if (this.#el('.xd-outline-panel').hidden) return;
    clearTimeout(this.#outlineTimer);
    this.#outlineTimer = setTimeout(() => this.#renderOutline(), 300);
  }

  #renderOutline() {
    const box = this.#el('.xd-outline');
    const lines = this.#editor().value.split('\n');
    const items = [];
    let inFence = false;
    lines.forEach((ln, i) => {
      if (/^\s*```/.test(ln)) inFence = !inFence;
      if (inFence) return;
      const m = ln.match(/^(#{1,6})\s+(.*)$/);
      if (m) items.push({ level: m[1].length, text: m[2].trim(), line: i });
    });
    box.replaceChildren();
    if (!items.length) {
      box.innerHTML = '<p class="xd-muted">No headings yet.</p>';
      return;
    }
    for (const it of items) {
      const b = document.createElement('button');
      b.className = `xd-outline-item lvl-${it.level}`;
      b.textContent = it.text || '(untitled)';
      b.addEventListener('click', () => this.#gotoLine(it.line));
      box.appendChild(b);
    }
  }

  #gotoLine(line) {
    const ed = this.#editor();
    const lines = ed.value.split('\n');
    const off = this.#offsetOfLine(line);
    ed.focus();
    ed.setSelectionRange(off, off + (lines[line]?.length || 0));
    this.#scrollToOffset(off);
    this.#updateCursor();
    this.#syncPreviewToCaret();
  }

  // ---- Line operations ----

  #lineBlockRange() {
    const ed = this.#editor();
    const v = ed.value;
    const start = v.lastIndexOf('\n', ed.selectionStart - 1) + 1;
    let end = v.indexOf('\n', ed.selectionEnd);
    if (end === -1) end = v.length;
    return { start, end };
  }

  #moveLines(dir) {
    const ed = this.#editor();
    const v = ed.value;
    const { start, end } = this.#lineBlockRange();
    const block = v.slice(start, end);
    const selOffStart = ed.selectionStart - start;
    const selOffEnd = ed.selectionEnd - start;
    if (dir < 0) {
      if (start === 0) return;
      const prevStart = v.lastIndexOf('\n', start - 2) + 1;
      const prevLine = v.slice(prevStart, start - 1);
      const replaced = `${block}\n${prevLine}`;
      this.#applyEdit(prevStart, end, replaced, prevStart + selOffStart, prevStart + selOffEnd);
    } else {
      if (end >= v.length) return;
      let nextEnd = v.indexOf('\n', end + 1);
      if (nextEnd === -1) nextEnd = v.length;
      const nextLine = v.slice(end + 1, nextEnd);
      const replaced = `${nextLine}\n${block}`;
      const shift = nextLine.length + 1;
      this.#applyEdit(start, nextEnd, replaced, start + shift + selOffStart, start + shift + selOffEnd);
    }
    this.#afterEdit();
  }

  #duplicateLines() {
    const ed = this.#editor();
    const { start, end } = this.#lineBlockRange();
    const block = ed.value.slice(start, end);
    const grow = block.length + 1;
    this.#applyEdit(end, end, `\n${block}`, ed.selectionStart + grow, ed.selectionEnd + grow);
    this.#afterEdit();
  }

  // ---- Auto-pairing of brackets / quotes ----

  #autoPair(e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return false;
    const pairs = { '(': ')', '[': ']', '{': '}', '`': '`', '"': '"', '*': '*', _: '_' };
    const close = pairs[e.key];
    if (!close) return false;
    const ed = this.#editor();
    const { selectionStart: s, selectionEnd: en } = ed;
    if (s !== en) {
      // Wrap the current selection in the typed delimiter.
      const sel = ed.value.slice(s, en);
      e.preventDefault();
      this.#applyEdit(s, en, e.key + sel + close, s + 1, s + 1 + sel.length);
      this.#afterEdit();
      return true;
    }
    // With no selection, only auto-close brackets (quotes/*/_ would fight Markdown).
    if ('([{'.includes(e.key)) {
      e.preventDefault();
      this.#applyEdit(s, en, e.key + close, s + 1);
      this.#afterEdit();
      return true;
    }
    return false;
  }

  // ---- Table tools ----

  #tableOp(op) {
    const ed = this.#editor();
    const lines = ed.value.split('\n');
    const caretLine = this.#lineOfOffset(ed.selectionStart);
    if (!/\|/.test(lines[caretLine] || '')) {
      this.#status('Place the caret inside a Markdown table.');
      return;
    }
    let top = caretLine;
    while (top > 0 && /\|/.test(lines[top - 1])) top -= 1;
    let bot = caretLine;
    while (bot < lines.length - 1 && /\|/.test(lines[bot + 1])) bot += 1;
    const splitRow = (ln) =>
      ln.replace(/^\s*\|?/, '').replace(/\|?\s*$/, '').split('|').map((c) => c.trim());
    const rows = [];
    for (let i = top; i <= bot; i += 1) rows.push(splitRow(lines[i]));
    const sepIdx = 1; // header row, separator row, then body
    const cols = Math.max(...rows.map((r) => r.length));
    const caretText = lines[caretLine].slice(0, ed.selectionStart - this.#offsetOfLine(caretLine));
    const caretCol = Math.max(0, (caretText.match(/\|/g) || []).length - 1);
    const relRow = caretLine - top;
    if (op === 'row') {
      rows.splice(Math.max(sepIdx + 1, relRow + 1), 0, Array(cols).fill('   '));
    } else if (op === 'delrow') {
      if (relRow !== sepIdx && rows.length > 3) rows.splice(relRow, 1);
    } else if (op === 'col') {
      rows.forEach((r, i) => r.splice(caretCol + 1, 0, i === sepIdx ? '---' : '   '));
    } else if (op === 'delcol') {
      if (cols > 1) rows.forEach((r) => r.splice(caretCol, 1));
    }
    const rebuilt = rows.map((r) => `| ${r.join(' | ')} |`).join('\n');
    const start = this.#offsetOfLine(top);
    const end = this.#offsetOfLine(bot) + lines[bot].length;
    this.#applyEdit(start, end, rebuilt, start);
  }

  // ---- Slash (`/`) insert menu ----

  #handleSlashInput() {
    const ed = this.#editor();
    const slash = this.#el('.xd-slash');
    const caret = ed.selectionStart;
    if (slash.hidden) {
      if (ed.value[caret - 1] === '/') {
        const lineStart = ed.value.lastIndexOf('\n', caret - 2) + 1;
        if (ed.value.slice(lineStart, caret - 1).trim() === '') {
          this.#slashStart = caret - 1;
          this.#showSlash('');
        }
      }
      return;
    }
    if (caret <= this.#slashStart || ed.value[this.#slashStart] !== '/') {
      this.#hideSlash();
      return;
    }
    const query = ed.value.slice(this.#slashStart + 1, caret);
    if (/\s/.test(query)) this.#hideSlash();
    else this.#showSlash(query);
  }

  #showSlash(query) {
    const q = query.toLowerCase();
    const items = SLASH_ITEMS.filter(
      (it) => !q || it.label.toLowerCase().includes(q) || it.key.includes(q)
    );
    const box = this.#el('.xd-slash');
    box.replaceChildren();
    if (!items.length) {
      this.#hideSlash();
      return;
    }
    this.#slashActive = 0;
    items.forEach((it, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = `xd-slash-item${i === 0 ? ' active' : ''}`;
      b.dataset.key = it.key;
      b.innerHTML = `<span class="xd-slash-ico">${it.icon}</span><span>${this.#esc(it.label)}</span>`;
      // mousedown (not click) so the editor keeps focus and selection.
      b.addEventListener('mousedown', (ev) => {
        ev.preventDefault();
        this.#runSlash(it.key);
      });
      box.appendChild(b);
    });
    this.#positionSlash();
    box.hidden = false;
  }

  #positionSlash() {
    const ed = this.#editor();
    const box = this.#el('.xd-slash');
    const admin = this.#el('.xd-admin');
    const edRect = ed.getBoundingClientRect();
    const adminRect = admin.getBoundingClientRect();
    const lh = parseFloat(window.getComputedStyle(ed).lineHeight) || 18;
    const line = this.#lineOfOffset(this.#slashStart);
    const top = edRect.top - adminRect.top + line * lh - ed.scrollTop + lh + 4;
    box.style.top = `${Math.max(4, top)}px`;
    box.style.left = `${edRect.left - adminRect.left + 12}px`;
  }

  #hideSlash() {
    this.#el('.xd-slash').hidden = true;
    this.#slashStart = -1;
  }

  #onSlashKey(e) {
    const box = this.#el('.xd-slash');
    const items = [...box.querySelectorAll('.xd-slash-item')];
    if (!items.length) return false;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      this.#slashActive = (this.#slashActive + 1) % items.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      this.#slashActive = (this.#slashActive - 1 + items.length) % items.length;
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      this.#runSlash(items[this.#slashActive].dataset.key);
      return true;
    } else if (e.key === 'Escape') {
      e.preventDefault();
      this.#hideSlash();
      return true;
    } else {
      return false;
    }
    items.forEach((it, i) => it.classList.toggle('active', i === this.#slashActive));
    return true;
  }

  #runSlash(key) {
    const ed = this.#editor();
    // Remove the typed "/query" before applying the chosen block.
    this.#applyEdit(this.#slashStart, ed.selectionStart, '');
    this.#hideSlash();
    if (key === 'h1' || key === 'h2' || key === 'h3') this.#setBlock(key[1]);
    else if (['ul', 'ol', 'task', 'quote'].includes(key)) this.#listPrefix(key);
    else if (key === 'code') this.#mdAction('codeblock');
    else this.#mdAction(key); // table / hr / mermaid / math / link
    this.#afterEdit();
  }

  // ---- Emoji / special-character picker ----

  #buildEmoji() {
    const box = this.#el('.xd-emoji');
    for (const c of EMOJI_CHARS) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = c;
      b.addEventListener('click', () => {
        this.#el('.xd-emoji').hidden = true;
        this.#insertText(c);
        this.#afterEdit();
      });
      box.appendChild(b);
    }
  }

  #positionEmoji() {
    const btn = this.#el('.xd-emoji-btn');
    const box = this.#el('.xd-emoji');
    const admin = this.#el('.xd-admin');
    const bRect = btn.getBoundingClientRect();
    const adminRect = admin.getBoundingClientRect();
    box.style.top = `${bRect.bottom - adminRect.top + 4}px`;
    box.style.left = `${bRect.left - adminRect.left}px`;
  }

  // ---- Editor ↔ preview sync ----

  #indexPreviewBlocks() {
    const preview = this.#el('.xd-preview');
    this.#previewBlocks = [...preview.querySelectorAll('[data-sl]')]
      .map((el) => ({ el, line: parseInt(el.getAttribute('data-sl'), 10) }))
      .filter((b) => Number.isFinite(b.line))
      .sort((a, b) => a.line - b.line);
    this.#syncPreviewToCaret();
  }

  /** The deepest preview block whose start line is ≤ `line` (most specific match). */
  #blockForLine(line) {
    let target = null;
    for (const b of this.#previewBlocks) {
      if (b.line <= line) target = b;
      else break;
    }
    return target;
  }

  #blockTop(el) {
    const preview = this.#el('.xd-preview');
    return el.getBoundingClientRect().top - preview.getBoundingClientRect().top + preview.scrollTop;
  }

  #highlightPreviewBlock(el, scroll = false) {
    const preview = this.#el('.xd-preview');
    preview.querySelectorAll('.xd-sl-active').forEach((n) => n.classList.remove('xd-sl-active'));
    if (!el) return;
    el.classList.add('xd-sl-active');
    if (scroll) {
      this.#syncGuard = true;
      el.scrollIntoView({ block: 'nearest' });
      window.requestAnimationFrame(() => (this.#syncGuard = false));
    }
  }

  /** Editor caret → highlight (and scroll to) the matching preview block. */
  #syncPreviewToCaret() {
    if (!this.#syncOn || !this.#previewBlocks.length) return;
    const target = this.#blockForLine(this.#lineOfOffset(this.#editor().selectionStart));
    this.#highlightPreviewBlock(target?.el, true);
  }

  /** Preview click → select the originating Markdown source lines in the editor. */
  #syncCaretFromPreview(e) {
    if (!this.#syncOn || this.#editor().readOnly) return;
    const block = e.target.closest?.('[data-sl]');
    if (!block) return;
    const startLine = parseInt(block.getAttribute('data-sl'), 10);
    if (!Number.isFinite(startLine)) return;
    const ed = this.#editor();
    const lines = ed.value.split('\n');
    const next = this.#previewBlocks.find((b) => b.line > startLine);
    const endLine = Math.min(next ? next.line - 1 : lines.length - 1, lines.length - 1);
    const start = this.#offsetOfLine(startLine);
    const end = this.#offsetOfLine(endLine) + (lines[endLine] || '').length;
    ed.focus();
    ed.setSelectionRange(start, end);
    this.#scrollToOffset(start);
    this.#highlightPreviewBlock(block);
    this.#updateCursor();
  }

  /** Keep the two panes scrolled together (toggleable; guarded against feedback). */
  #syncScroll(source) {
    if (!this.#syncOn || this.#syncGuard || !this.#previewBlocks.length) return;
    const ed = this.#editor();
    const preview = this.#el('.xd-preview');
    const lh = parseFloat(window.getComputedStyle(ed).lineHeight) || 18;
    this.#syncGuard = true;
    if (source === 'editor') {
      const target = this.#blockForLine(Math.round(ed.scrollTop / lh)) || this.#previewBlocks[0];
      preview.scrollTop = Math.max(0, this.#blockTop(target.el));
    } else {
      let target = this.#previewBlocks[0];
      for (const b of this.#previewBlocks) {
        if (this.#blockTop(b.el) <= preview.scrollTop + 1) target = b;
        else break;
      }
      ed.scrollTop = target.line * lh;
    }
    window.requestAnimationFrame(() => (this.#syncGuard = false));
  }

  /** Parse a PDF server-side and insert its Markdown (text + images) at the caret. */
  async #importPdfIntoPage(file) {
    if (!this.#pageId) {
      this.#status('Open a page before importing a PDF.');
      return;
    }
    this.#status('Importing PDF…');
    try {
      const token = await this.#tokenProvider();
      const form = new FormData();
      form.append('file', file);
      const resp = await fetch(
        `${this.baseUrl}/api/v1/admin/spaces/${this.space}/import-pdf-markdown`,
        { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form }
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const { markdown } = await resp.json();
      if (markdown) {
        this.#insertBlock(markdown);
        this.#afterEdit();
        this.#status('PDF imported');
      } else {
        this.#status('No extractable content in the PDF.');
      }
    } catch (err) {
      this.#status(`Import failed: ${err.message}`);
    }
  }

  /** Rewrite the info string of the fenced code block containing the caret. */
  #setCodeFenceLang(lang) {
    const ed = this.#editor();
    const v = ed.value;
    const lines = v.split('\n');
    // Map caret offset to a line index.
    let pos = 0;
    let caretLine = 0;
    for (let i = 0; i < lines.length; i += 1) {
      if (pos + lines[i].length >= ed.selectionStart) {
        caretLine = i;
        break;
      }
      pos += lines[i].length + 1; // + newline
    }
    // Find the nearest ``` fence opener at or above the caret.
    let opener = -1;
    let fenced = false;
    for (let i = caretLine; i >= 0; i -= 1) {
      if (/^\s*```/.test(lines[i])) {
        // Count fences above i to know if line i is an opener (even index).
        let count = 0;
        for (let j = 0; j < i; j += 1) if (/^\s*```/.test(lines[j])) count += 1;
        if (count % 2 === 0) {
          opener = i;
          fenced = true;
        }
        break;
      }
    }
    if (!fenced || opener < 0) {
      this.#status('Place the caret inside a code block to set its language.');
      return;
    }
    let lineStart = 0;
    for (let i = 0; i < opener; i += 1) lineStart += lines[i].length + 1;
    const oldLine = lines[opener];
    const newLine = oldLine.replace(/^(\s*```)[^\n]*$/, `$1${lang}`);
    const caret = Math.max(0, ed.selectionStart + (newLine.length - oldLine.length));
    this.#applyEdit(lineStart, lineStart + oldLine.length, newLine, caret);
    this.#afterEdit();
  }

  /** Append/update a `{width= align=}` attribute block on the image at the caret. */
  #imageOptions() {
    const ed = this.#editor();
    const v = ed.value;
    // Find an image markup `![..](..)` (optionally followed by `{...}`) under caret.
    const re = /!\[[^\]]*\]\([^)]*\)(\{[^}]*\})?/g;
    let m;
    let target = null;
    while ((m = re.exec(v)) !== null) {
      if (ed.selectionStart >= m.index && ed.selectionStart <= m.index + m[0].length) {
        target = m;
        break;
      }
    }
    if (!target) {
      this.#status('Place the caret on an image to resize/position it.');
      return;
    }
    // Pre-fill the prompts from any attributes already on the image.
    const cur = target[1] || '';
    const attr = (k) => (cur.match(new RegExp(`${k}=([^\\s}]+)`)) || [])[1] || '';
    const width = this.#prompt('Image width in px (blank = auto)', attr('width') || '320');
    if (width === null) return;
    const height = this.#prompt('Image height in px (blank = auto)', attr('height'));
    if (height === null) return;
    const align = this.#prompt('Align: left, center, right (blank to clear)', attr('align') || 'center');
    if (align === null) return;
    const parts = [];
    if (width.trim()) parts.push(`width=${width.trim()}`);
    if (height.trim()) parts.push(`height=${height.trim()}`);
    if (['left', 'center', 'right'].includes(align.trim())) parts.push(`align=${align.trim()}`);
    const base = target[0].replace(/\{[^}]*\}$/, ''); // image without any existing attrs
    const replacement = parts.length ? `${base}{${parts.join(' ')}}` : base;
    this.#applyEdit(
      target.index,
      target.index + target[0].length,
      replacement,
      target.index + replacement.length
    );
    this.#afterEdit();
  }

  #wireBar() {
    this.#el('.xd-spaces-btn').addEventListener('click', () => {
      if (!this.#confirmDiscard()) return;
      this.#setDirty(false);
      this.#gotoBooks();
    });
    this.#el('.xd-view-btn').addEventListener('click', () => {
      if (!this.#confirmDiscard()) return;
      this.#setDirty(false);
      this.dispatchEvent(
        new CustomEvent('xdocs:view', { bubbles: true, composed: true, detail: { space: this.space } })
      );
    });
    this.#el('.xd-save').addEventListener('click', () => this.#save());
    this.#el('.xd-publish').addEventListener('click', () => this.#publish());
    this.#el('.xd-draft').addEventListener('click', () => this.#generateDraft());
    this.#el('.xd-approve').addEventListener('click', () => this.#approve());
    this.#el('.xd-discard').addEventListener('click', () => this.#discardDraft());
    this.#el('.xd-unpublish').addEventListener('click', () => this.#unpublish());
    this.#el('.xd-delete').addEventListener('click', () => this.#deletePage());

    // View modes.
    this.#shadow.querySelectorAll('.xd-viewmodes button').forEach((b) => {
      b.addEventListener('click', () => this.#setView(b.dataset.vm));
    });
    this.#el('.xd-zen').addEventListener('click', () => this.#toggleZen());
    this.#el('.xd-history').addEventListener('click', () => this.#toggleHistory());
    this.#el('.xd-revs-close').addEventListener('click', () => this.#toggleHistory(false));

    // "More" menu open/close.
    const more = this.#el('.xd-more');
    const menu = this.#el('.xd-menu');
    more.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    this.#shadow.addEventListener('click', (e) => {
      if (!e.composedPath().includes(this.#el('.xd-menu-wrap'))) menu.hidden = true;
    });
    this.#shadow.querySelectorAll('.xd-menu button').forEach((b) =>
      b.addEventListener('click', () => (menu.hidden = true))
    );

    // Esc exits fullscreen.
    this.#el('.xd-admin').addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.#el('.xd-admin').dataset.zen === 'true') this.#toggleZen(false);
    });
  }

  #wireLang() {
    const lang = this.#el('.xd-admin-lang');
    for (const loc of this.locales) {
      const opt = document.createElement('option');
      opt.value = loc;
      opt.textContent = loc.toUpperCase();
      lang.appendChild(opt);
    }
    lang.value = this.#editLocale;
    lang.addEventListener('change', () => {
      if (!this.#confirmDiscard()) {
        lang.value = this.#editLocale;
        return;
      }
      this.#editLocale = lang.value;
      if (this.#pageId) this.#openPage(this.#pageId);
    });
  }

  // ---- Spaces management ----

  #wireSpaces() {
    this.#el('.xd-new-space').addEventListener('click', () => this.#openSpaceForm(null));
    const form = this.#el('.xd-space-form');
    this.#el('.xd-sf-cancel').addEventListener('click', () => (form.hidden = true));
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      this.#saveSpace();
    });
    // Auto-fill the slug from the title until the user types their own slug.
    const slugInput = this.#el('.xd-sf-slug');
    this.#el('.xd-sf-title').addEventListener('input', (e) => {
      if (this.#editingSpace) return; // never rename the slug of an existing space
      if (!slugInput.dataset.touched) slugInput.value = slugify(e.target.value);
    });
    slugInput.addEventListener('input', () => (slugInput.dataset.touched = '1'));
    // Preset colour swatches.
    const sw = this.#el('.xd-sf-swatches');
    for (const c of XdocsAdmin.#PALETTE) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'xd-color-swatch';
      b.style.background = c;
      b.title = c;
      b.addEventListener('click', () => (this.#el('.xd-sf-color').value = c));
      sw.appendChild(b);
    }
  }

  async #loadSpaces() {
    if (!this.baseUrl || !this.#tokenProvider) return;
    const grid = this.#el('.xd-space-grid');
    try {
      const { items } = await this.#api('/admin/spaces');
      this.#spaces = items || [];
      this.#renderSpaces();
    } catch (err) {
      grid.innerHTML = `<p class="xd-muted">Error: ${err.message}</p>`;
    }
  }

  #renderSpaces() {
    const grid = this.#el('.xd-space-grid');
    grid.replaceChildren();
    if (!this.#spaces.length) {
      grid.innerHTML = '<p class="xd-muted">No spaces yet — create one.</p>';
      return;
    }
    for (const s of this.#spaces) {
      const card = document.createElement('div');
      card.className = 'xd-space-card';
      card.style.setProperty('--xd-space-color', s.color || 'var(--xdocs-color-primary)');

      const open = document.createElement('button');
      open.className = 'xd-space-open';
      open.innerHTML =
        `<span class="xd-space-title">${this.#esc(s.title)}</span>` +
        `<span class="xd-space-desc">${this.#esc(s.description || '')}</span>` +
        `<span class="xd-space-meta">${s.book_count} book(s) · ${s.page_count} page(s)</span>`;
      open.addEventListener('click', () => this.#openSpace(s.slug));

      const actions = document.createElement('div');
      actions.className = 'xd-space-actions';
      const mk = (label, title, handler, cls = '') => {
        const b = document.createElement('button');
        b.textContent = label;
        b.title = title;
        if (cls) b.className = cls;
        b.addEventListener('click', (e) => {
          e.stopPropagation();
          handler();
        });
        return b;
      };
      actions.append(
        mk('✎', 'Edit space', () => this.#openSpaceForm(s)),
        mk('⤓', 'Archive (zip)', () => this.#archiveSpace(s.slug)),
        mk('🗑', 'Delete space', () => this.#deleteSpace(s.slug), 'danger')
      );

      card.append(open, actions);
      grid.appendChild(card);
    }
  }

  #openSpaceForm(space) {
    const form = this.#el('.xd-space-form');
    this.#editingSpace = space ? space.slug : null;
    const slugInput = this.#el('.xd-sf-slug');
    this.#el('.xd-sf-title').value = space?.title || '';
    slugInput.value = space?.slug || '';
    slugInput.disabled = !!space; // slug is the stable identifier; don't rename it
    slugInput.dataset.touched = space ? '1' : '';
    this.#el('.xd-sf-desc').value = space?.description || '';
    this.#el('.xd-sf-locale').value = space?.default_locale || 'en';
    this.#el('.xd-sf-color').value = space?.color || '#0b5cad';
    this.#el('.xd-sf-status').textContent = '';
    form.hidden = false;
    this.#el('.xd-sf-title').focus();
  }

  async #saveSpace() {
    const title = this.#el('.xd-sf-title').value.trim();
    const slug = slugify(this.#el('.xd-sf-slug').value || title);
    const body = {
      title,
      description: this.#el('.xd-sf-desc').value.trim(),
      color: this.#el('.xd-sf-color').value,
      default_locale: this.#el('.xd-sf-locale').value.trim() || 'en',
    };
    if (!title) {
      this.#el('.xd-sf-status').textContent = 'Title is required.';
      return;
    }
    try {
      if (this.#editingSpace) {
        await this.#api(`/admin/spaces/${this.#editingSpace}`, {
          method: 'PUT',
          body: JSON.stringify(body),
        });
      } else {
        await this.#api('/admin/spaces', {
          method: 'POST',
          body: JSON.stringify({ slug, ...body }),
        });
      }
      this.#el('.xd-space-form').hidden = true;
      this.#loadSpaces();
    } catch (err) {
      this.#el('.xd-sf-status').textContent =
        err.status === 403 ? 'Admin permission required.' : `Error: ${err.message}`;
    }
  }

  async #deleteSpace(slug) {
    const ok = (() => {
      try {
        return window.confirm(`Delete space “${slug}” and all its content? This cannot be undone.`);
      } catch {
        return true;
      }
    })();
    if (!ok) return;
    try {
      await this.#api(`/admin/spaces/${slug}`, { method: 'DELETE' });
      this.#loadSpaces();
    } catch (err) {
      window.alert?.(err.status === 403 ? 'Admin permission required.' : `Error: ${err.message}`);
    }
  }

  async #archiveSpace(slug) {
    try {
      const token = await this.#tokenProvider();
      const resp = await fetch(`${this.baseUrl}/api/v1/admin/spaces/${slug}/archive`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${slug}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      window.alert?.(`Archive failed: ${err.message}`);
    }
  }

  #esc(s) {
    return String(s).replace(
      /[&<>"]/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]
    );
  }

  // ---- Books screen ----

  #wireBooks() {
    this.#el('.xd-books-back').addEventListener('click', () => this.#gotoSpaces());
    this.#el('.xd-new-book').addEventListener('click', () => this.#newBook());
    this.#el('.xd-import-book').addEventListener('click', () => this.#importBookPdf());
  }

  async #loadBooks() {
    if (!this.baseUrl || !this.#tokenProvider || !this.space) return;
    const grid = this.#el('.xd-book-grid');
    try {
      const tree = await this.#api(`/admin/spaces/${this.space}/tree`);
      this.#spaceMeta = { title: tree.title, color: tree.color };
      this.#books = tree.books || [];
      this.#el('.xd-books-title').textContent = tree.title ? `Books · ${tree.title}` : 'Books';
      this.#renderBooks();
    } catch (err) {
      grid.innerHTML = `<p class="xd-muted">Error: ${err.message}</p>`;
    }
  }

  #renderBooks() {
    const grid = this.#el('.xd-book-grid');
    grid.replaceChildren();
    if (!this.#books.length) {
      grid.innerHTML = '<p class="xd-muted">No books yet — add one or import a PDF.</p>';
      return;
    }
    for (const b of this.#books) {
      const sectionCount = (b.sections || []).length;
      const pageCount =
        (b.pages || []).length +
        (b.sections || []).reduce((n, s) => n + (s.pages || []).length, 0);
      const card = document.createElement('div');
      card.className = 'xd-space-card';
      card.style.setProperty(
        '--xd-space-color',
        this.#spaceMeta?.color || 'var(--xdocs-color-primary)'
      );

      const open = document.createElement('button');
      open.className = 'xd-space-open';
      open.innerHTML =
        `<span class="xd-space-title">${this.#esc(b.title)}</span>` +
        `<span class="xd-space-meta">${sectionCount} section(s) · ${pageCount} page(s)</span>`;
      open.addEventListener('click', () => this.#openBook(b.id));

      const actions = document.createElement('div');
      actions.className = 'xd-space-actions';
      const mk = (label, title, handler, cls = '') => {
        const x = document.createElement('button');
        x.textContent = label;
        x.title = title;
        if (cls) x.className = cls;
        x.addEventListener('click', (e) => {
          e.stopPropagation();
          handler();
        });
        return x;
      };
      actions.append(
        mk('✎', 'Rename book', () => this.#renameBook(b)),
        mk('⤓', 'Export book (zip)', () => this.#exportBook(b.id)),
        mk('🗑', 'Delete book', () => this.#deleteBook(b.id), 'danger')
      );
      card.append(open, actions);
      grid.appendChild(card);
    }
  }

  async #newBook() {
    const title = this.#prompt('New book title');
    if (!title) return;
    try {
      const book = await this.#api(`/admin/spaces/${this.space}/books`, {
        method: 'POST',
        body: JSON.stringify({ title }),
      });
      await this.#loadBooks();
      this.#openBook(book.id);
    } catch (err) {
      this.#el('.xd-book-grid').insertAdjacentHTML(
        'afterbegin',
        `<p class="xd-muted">Error: ${err.message}</p>`
      );
    }
  }

  #importBookPdf() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/pdf,.pdf';
    input.addEventListener('change', () => {
      if (input.files[0]) this.#doImportBookPdf(input.files[0]);
    });
    input.click();
  }

  async #doImportBookPdf(file) {
    const grid = this.#el('.xd-book-grid');
    grid.insertAdjacentHTML('afterbegin', `<p class="xd-muted">Importing ${file.name}…</p>`);
    try {
      const token = await this.#tokenProvider();
      const form = new FormData();
      form.append('file', file);
      form.append('locale', this.#editLocale);
      const resp = await fetch(`${this.baseUrl}/api/v1/admin/spaces/${this.space}/books/import-pdf`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!resp.ok) {
        let detail = `HTTP ${resp.status}`;
        try {
          detail = (await resp.json())?.error?.message || detail;
        } catch {
          /* keep status code */
        }
        throw new Error(detail);
      }
      const { book } = await resp.json();
      await this.#loadBooks();
      if (book?.id) this.#openBook(book.id);
    } catch (err) {
      grid.insertAdjacentHTML('afterbegin', `<p class="xd-muted">Import failed: ${err.message}</p>`);
    }
  }

  async #exportBook(bookId) {
    try {
      const token = await this.#tokenProvider();
      const resp = await fetch(`${this.baseUrl}/api/v1/admin/books/${bookId}/archive`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `book-${bookId}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      window.alert?.(`Export failed: ${err.message}`);
    }
  }

  // ---- Navigation between screens ----

  #openSpace(slug) {
    this.#pageId = null;
    this.#bookId = null;
    this.#mode = 'books';
    if (this.space === slug) {
      this.#applyMode();
      this.#loadBooks();
    } else {
      this.setAttribute('space', slug); // → attributeChangedCallback → #boot (books mode)
    }
  }

  #openBook(bookId) {
    this.#pageId = null;
    this.#bookId = bookId;
    this.#mode = 'editor';
    this.#applyMode();
    this.#loadTree();
  }

  #gotoBooks() {
    this.#pageId = null;
    this.#bookId = null;
    this.#mode = 'books';
    this.#applyMode();
    this.#loadBooks();
  }

  #gotoSpaces() {
    this.#pageId = null;
    this.#bookId = null;
    this.#mode = 'spaces';
    this.#applyMode();
    if (this.hasAttribute('space')) this.removeAttribute('space'); // → #boot → #loadSpaces
    else this.#loadSpaces();
  }

  // ---- View modes / panels ----

  #setView(mode) {
    this.#el('.xd-admin').dataset.view = mode;
    this.#shadow
      .querySelectorAll('.xd-viewmodes button')
      .forEach((b) => b.classList.toggle('active', b.dataset.vm === mode));
    if (mode !== 'write') this.#schedulePreview(0);
  }

  #toggleZen(force) {
    const root = this.#el('.xd-admin');
    const on = force ?? root.dataset.zen !== 'true';
    root.dataset.zen = String(on);
  }

  #toggleHistory(force) {
    const panel = this.#el('.xd-revs-panel');
    const show = force ?? panel.hidden;
    panel.hidden = !show;
    if (show) this.#loadRevisions();
  }

  // ---- Status / counts / dirty ----

  #status(msg) {
    const el = this.#el('.xd-admin-status');
    if (el) el.textContent = msg;
  }

  #updateCounts() {
    const text = this.#editor().value;
    const words = (text.trim().match(/\S+/g) || []).length;
    const mins = Math.max(1, Math.ceil(words / 200));
    this.#el('.xd-counts').textContent = `${words} words · ${text.length} chars · ${mins} min read`;
  }

  #updateBadge() {
    const el = this.#el('.xd-status-badge');
    if (!this.#pageId) {
      el.textContent = '';
      el.dataset.s = '';
      return;
    }
    const base = this.#pageStatus === 'published' ? 'Published' : 'Draft';
    el.dataset.s = this.#pageStatus || 'draft';
    el.classList.toggle('dirty', this.#dirty);
    el.textContent = this.#dirty ? `${base} • unsaved` : base;
  }

  #setDirty(v) {
    this.#dirty = v;
    this.#updateBadge();
    if (v) window.addEventListener('beforeunload', this.#beforeUnload);
    else window.removeEventListener('beforeunload', this.#beforeUnload);
  }

  #confirmDiscard() {
    if (!this.#dirty) return true;
    try {
      return window.confirm('You have unsaved changes. Discard them?');
    } catch {
      return true;
    }
  }

  #afterEdit() {
    this.#setDirty(true);
    this.#updateCounts();
    this.#schedulePreview();
  }

  #schedulePreview(delay = 250) {
    clearTimeout(this.#previewTimer);
    this.#previewTimer = setTimeout(() => this.#preview(this.#editor().value), delay);
  }

  // ---- Editor helpers ----

  /**
   * Replace [start, end) in the editor with `text`, preserving the browser's native
   * undo/redo history via execCommand('insertText'). Falls back to setRangeText when
   * execCommand is unavailable (jsdom/tests) — the value is still correct, only the
   * undo stack is not retained there. Optionally re-selects [selStart, selEnd) after.
   */
  #applyEdit(start, end, text, selStart = null, selEnd = selStart) {
    const ed = this.#editor();
    ed.focus();
    ed.setSelectionRange(start, end);
    let ok = false;
    try {
      ok = document.execCommand('insertText', false, text);
    } catch {
      ok = false;
    }
    if (!ok) ed.setRangeText(text, start, end, 'end');
    if (selStart !== null) ed.setSelectionRange(selStart, selEnd);
  }

  #insertText(text) {
    const ed = this.#editor();
    const { selectionStart: s, selectionEnd: e } = ed;
    this.#applyEdit(s, e, text, s + text.length);
  }

  /** Wrap the selection in `before`/`after`, or toggle the markers off if they are
   *  already present (inside or just outside the selection) — e.g. bold ↔ un-bold. */
  #wrapSelection(before, after = before) {
    const ed = this.#editor();
    const { selectionStart: s, selectionEnd: e, value } = ed;
    const sel = value.slice(s, e);
    // Toggle off: the selection itself already carries the markers.
    if (
      sel.length >= before.length + after.length &&
      sel.startsWith(before) &&
      sel.endsWith(after)
    ) {
      const inner = sel.slice(before.length, sel.length - after.length);
      this.#applyEdit(s, e, inner, s, s + inner.length);
      return;
    }
    // Toggle off: the markers sit immediately around the selection.
    if (value.slice(s - before.length, s) === before && value.slice(e, e + after.length) === after) {
      const a = s - before.length;
      this.#applyEdit(a, e + after.length, sel, a, a + sel.length);
      return;
    }
    const body = sel || 'text';
    this.#applyEdit(s, e, before + body + after, s + before.length, s + before.length + body.length);
  }

  /** Apply a transform to each line overlapping the current selection. */
  #eachSelectedLine(transform) {
    const ed = this.#editor();
    const v = ed.value;
    const start = v.lastIndexOf('\n', ed.selectionStart - 1) + 1;
    let end = v.indexOf('\n', ed.selectionEnd);
    if (end === -1) end = v.length;
    const block = v.slice(start, end).split('\n').map(transform).join('\n');
    this.#applyEdit(start, end, block, start, start + block.length);
  }

  #setBlock(level) {
    if (level === 'quote') return this.#listPrefix('quote');
    if (level === 'code') {
      const ed = this.#editor();
      const { selectionStart: s, selectionEnd: e, value } = ed;
      const sel = value.slice(s, e) || 'code';
      const lang = this.#el('.xd-code-lang')?.value || '';
      const open = '```' + lang + '\n';
      const text = `${open}${sel}\n\`\`\``;
      return this.#applyEdit(s, e, text, s + open.length, s + open.length + sel.length);
    }
    return this.#eachSelectedLine((ln) => {
      const text = ln.replace(/^\s*(?:#{1,6}\s+|>\s+)/, '');
      return level === 'p' ? text : `${'#'.repeat(Number(level))} ${text}`;
    });
  }

  #listPrefix(kind) {
    let n = 0;
    this.#eachSelectedLine((ln) => {
      const text = ln.replace(/^\s*(?:[-*]\s+\[[ xX]\]|[-*]|\d+\.|>)\s+/, '');
      if (kind === 'ul') return `- ${text}`;
      if (kind === 'ol') return `${++n}. ${text}`;
      if (kind === 'task') return `- [ ] ${text}`;
      if (kind === 'quote') return `> ${text}`;
      return text;
    });
  }

  #insertBlock(text) {
    const ed = this.#editor();
    const before = ed.value.slice(0, ed.selectionStart);
    const lead = before && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : '';
    this.#insertText(`${lead}${text}\n\n`);
  }

  #mdAction(kind) {
    switch (kind) {
      case 'bold':
        return this.#wrapSelection('**');
      case 'italic':
        return this.#wrapSelection('_');
      case 'strike':
        return this.#wrapSelection('~~');
      case 'code':
        return this.#wrapSelection('`');
      case 'link':
        return this.#wrapSelection('[', '](https://)');
      case 'ul':
      case 'ol':
      case 'task':
      case 'quote':
        return this.#listPrefix(kind);
      case 'codeblock': {
        const lang = this.#el('.xd-code-lang')?.value || '';
        return this.#insertBlock('```' + lang + '\ncode\n```');
      }
      case 'table':
        return this.#insertBlock(TABLE_TEMPLATE);
      case 'hr':
        return this.#insertBlock('---');
      case 'mermaid':
        return this.#insertBlock('```mermaid\nflowchart LR\n  A[Start] --> B[End]\n```');
      case 'math':
        return this.#insertBlock('$$\nE = mc^2\n$$');
      default:
        return undefined;
    }
  }

  #onEditorKey(e) {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && !e.shiftKey && !e.altKey) {
      const k = e.key.toLowerCase();
      const inline = { b: 'bold', i: 'italic', k: 'link' }[k];
      if (inline) {
        e.preventDefault();
        this.#mdAction(inline);
        return this.#afterEdit();
      }
      if (k === 's') {
        e.preventDefault();
        return this.#save();
      }
      if (k === 'f') {
        e.preventDefault();
        return this.#openFind();
      }
      if (k === 'h') {
        e.preventDefault();
        return this.#openFind();
      }
      if (k === 'd') {
        e.preventDefault();
        return this.#duplicateLines();
      }
    }
    // Move / duplicate the current line(s) with Alt+Arrow (VS Code / Word-like).
    if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      if (e.shiftKey && e.key === 'ArrowDown') return this.#duplicateLines();
      return this.#moveLines(e.key === 'ArrowUp' ? -1 : 1);
    }
    // Slash menu navigation takes priority while it is open.
    if (!this.#el('.xd-slash').hidden && this.#onSlashKey(e)) return undefined;
    if (this.#autoPair(e)) return undefined;
    if (e.key === 'Tab') {
      e.preventDefault();
      if (e.shiftKey) this.#eachSelectedLine((ln) => ln.replace(/^ {1,2}/, ''));
      else this.#insertText('  ');
      return this.#afterEdit();
    }
    if (e.key === 'Enter') return this.#onEnter(e);
    return undefined;
  }

  /** Continue or end a Markdown list on Enter. */
  #onEnter(e) {
    const ed = this.#editor();
    const v = ed.value;
    const start = v.lastIndexOf('\n', ed.selectionStart - 1) + 1;
    const line = v.slice(start, ed.selectionStart);
    const m = line.match(/^(\s*)(- \[[ xX]\]|[-*]|\d+\.)\s+/);
    if (!m) return undefined;
    e.preventDefault();
    if (line.slice(m[0].length).trim() === '') {
      // Empty item: end the list by clearing the marker.
      this.#applyEdit(start, ed.selectionStart, '', start);
    } else {
      let marker = m[2];
      if (/^\d+\.$/.test(marker)) marker = `${parseInt(marker, 10) + 1}.`;
      else if (marker.startsWith('- [')) marker = '- [ ]';
      this.#insertText(`\n${m[1]}${marker} `);
    }
    return this.#afterEdit();
  }

  #onPaste(e) {
    const cd = e.clipboardData;
    if (!cd) return;
    // 1) Rich HTML (Word / Excel / web) -> down-convert to Markdown. Preferred
    //    over an image item so a copied Word/Excel range keeps its formatting;
    //    a bare screenshot has no text/html and falls through to (2).
    const html = cd.getData?.('text/html');
    if (html && html.trim()) {
      let md = '';
      try {
        md = htmlToMarkdown(html);
      } catch {
        md = '';
      }
      if (md) {
        e.preventDefault();
        if (md.includes('\n')) this.#insertBlock(md);
        else this.#insertText(md);
        this.#afterEdit();
        return;
      }
    }
    // 2) An image on the clipboard (screenshot, "copy image", or a Word image
    //    whose HTML had no usable web src) -> upload + insert a reference.
    const item = [...(cd.items || [])].find((i) => i.type.startsWith('image/'));
    const file = item?.getAsFile();
    if (file) {
      e.preventDefault();
      this.#uploadImage(file).then(() => this.#afterEdit());
    }
  }

  #onDrop(e) {
    const file = [...(e.dataTransfer?.files || [])].find((f) => f.type.startsWith('image/'));
    if (file) {
      e.preventDefault();
      this.#uploadImage(file).then(() => this.#afterEdit());
    }
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

  // ---- Tree ----

  async #loadTree() {
    if (!this.baseUrl || !this.#tokenProvider || !this.space) return;
    try {
      const tree = await this.#api(`/admin/spaces/${this.space}/tree`);
      this.#spaceMeta = { title: tree.title, color: tree.color };
      this.#books = tree.books || [];
      // Resolve which single book to show: the one holding a pending deep-link
      // page (reader → edit), else the already-open book, else the first.
      if (this.#pendingPageId) {
        const owner = this.#books.find((b) => this.#bookHasPage(b, this.#pendingPageId));
        if (owner) this.#bookId = owner.id;
      }
      if (!this.#books.some((b) => b.id === this.#bookId)) {
        this.#bookId = this.#books[0]?.id ?? null;
      }
      this.#renderTree();
      this.#tryOpenPending();
    } catch (err) {
      this.#el('.xd-admin-tree').textContent = `Error: ${err.message}`;
    }
  }

  #bookHasPage(book, pageId) {
    const hit = (pages) =>
      (pages || []).some((p) => p.id === pageId || hit(p.children));
    return hit(book.pages) || (book.sections || []).some((s) => hit(s.pages));
  }

  #activeBook() {
    return this.#books.find((b) => b.id === this.#bookId) || null;
  }

  #tryOpenPending() {
    if (!this.#pendingPageId) return;
    const found = this.#shadow.querySelector(
      `.xd-admin-tree button.page[data-page="${this.#pendingPageId}"]`
    );
    if (found) {
      const id = this.#pendingPageId;
      this.#pendingPageId = null;
      this.#openPage(id);
    }
  }

  /** A small text button used in book/section headers. */
  #treeBtn(label, title, handler, cls = 'xd-newpage') {
    const b = document.createElement('button');
    b.className = cls;
    b.textContent = label;
    b.title = title;
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      handler();
    });
    return b;
  }

  /** Render the sidebar for the single active book (sections + pages). */
  #renderTree() {
    const nav = this.#el('.xd-admin-tree');
    nav.replaceChildren();

    const back = document.createElement('button');
    back.className = 'xd-tree-back';
    back.textContent = '← Books';
    back.title = 'Back to books';
    back.addEventListener('click', () => this.#gotoBooks());
    nav.appendChild(back);

    if (this.#spaceMeta?.title) {
      const sh = document.createElement('div');
      sh.className = 'xd-tree-space';
      sh.style.setProperty('--xd-space-color', this.#spaceMeta.color || 'var(--xdocs-color-primary)');
      sh.textContent = this.#spaceMeta.title;
      nav.appendChild(sh);
    }

    const book = this.#activeBook();
    if (!book) {
      nav.insertAdjacentHTML('beforeend', '<p class="xd-muted">No book selected.</p>');
      return;
    }
    nav.appendChild(this.#bookHead(book));
    for (const sec of book.sections || []) {
      nav.appendChild(this.#sectionHead(sec, book.id));
      for (const p of sec.pages) this.#appendPageRows(nav, p, book.id);
    }
    for (const p of book.pages) this.#appendPageRows(nav, p, book.id);
  }

  #bookHead(book) {
    const head = document.createElement('div');
    head.className = 'xd-admin-book';
    const label = document.createElement('span');
    label.className = 'xd-book-title';
    label.textContent = book.title;
    const acts = document.createElement('span');
    acts.className = 'xd-tree-act';
    acts.append(
      this.#treeBtn('+ Page', 'Add a page', () => this.#newPage(book.id, null)),
      this.#treeBtn('+ Section', 'Add a section', () => this.#newSection(book.id))
    );
    head.append(label, acts);
    return head;
  }

  #sectionHead(sec, bookId) {
    const head = document.createElement('div');
    head.className = 'xd-section';
    const label = document.createElement('span');
    label.className = 'xd-section-title';
    label.textContent = sec.title;
    const acts = document.createElement('span');
    acts.className = 'xd-tree-act';
    acts.append(
      this.#treeBtn('+ Page', 'Add a page to this section', () => this.#newPage(bookId, sec.id)),
      this.#treeBtn('✎', 'Rename section', () => this.#renameSection(sec)),
      this.#treeBtn('🗑', 'Delete section', () => this.#deleteSection(sec.id), 'xd-newpage danger')
    );
    head.append(label, acts);
    return head;
  }

  /** A published page with unpublished edits shows two rows (Published + Draft);
   *  otherwise a single row reflecting the page's status. */
  #appendPageRows(nav, p, bookId) {
    if (p.has_draft) {
      nav.appendChild(this.#pageRowEl(p, bookId, nav, 'published'));
      nav.appendChild(this.#pageRowEl(p, bookId, nav, 'draft'));
    } else {
      nav.appendChild(this.#pageRowEl(p, bookId, nav, 'single'));
    }
  }

  #pageRowEl(p, bookId, nav, variant) {
    const editable = variant !== 'published'; // the Published row mirrors the live copy
    const badgeStatus = variant === 'published' ? 'published' : variant === 'draft' ? 'draft' : p.status;

    const row = document.createElement('div');
    row.className = 'xd-page-row';
    row.dataset.page = p.id;
    row.dataset.variant = variant;
    if (editable) {
      row.dataset.book = bookId; // only editable rows take part in drag-reorder
      row.draggable = true;
    }

    const open = document.createElement('button');
    open.className = 'page';
    open.dataset.page = p.id;
    open.dataset.variant = variant;
    const title = document.createElement('span');
    title.className = 'xd-page-title';
    title.textContent = p.title;
    const badge = document.createElement('span');
    badge.className = `xd-badge ${badgeStatus}`;
    badge.textContent = badgeStatus;
    open.append(title, badge);
    open.addEventListener('click', () => this.#openPage(p.id, { published: variant === 'published' }));

    row.append(open);
    if (editable) {
      const acts = document.createElement('span');
      acts.className = 'xd-tree-act';
      acts.append(
        this.#treeBtn('✎', 'Rename page', () => this.#renamePage(p), 'xd-row-act'),
        this.#treeBtn('🗑', 'Delete page', () => this.#deletePageById(p.id), 'xd-row-act danger')
      );
      row.append(acts);
      this.#wireDrag(row, nav);
    }
    return row;
  }

  #wireDrag(row, nav) {
    row.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', row.dataset.page);
      row.classList.add('dragging');
    });
    row.addEventListener('dragend', () => row.classList.remove('dragging'));
    row.addEventListener('dragover', (e) => e.preventDefault());
    row.addEventListener('drop', (e) => {
      e.preventDefault();
      const draggedId = e.dataTransfer.getData('text/plain');
      const dragged = nav.querySelector(`.xd-page-row[data-page="${draggedId}"]`);
      if (!dragged || dragged === row || dragged.dataset.book !== row.dataset.book) return;
      nav.insertBefore(dragged, row); // reorder in the DOM, then persist
      this.#persistOrder(row.dataset.book, nav);
    });
  }

  async #persistOrder(bookId, nav) {
    const items = [...nav.querySelectorAll(`.xd-page-row[data-book="${bookId}"]`)].map((b, i) => ({
      id: b.dataset.page,
      sort_order: i,
    }));
    try {
      await this.#api('/admin/pages/reorder', { method: 'POST', body: JSON.stringify({ items }) });
      this.#status('reordered');
    } catch (err) {
      this.#status(`Reorder failed: ${err.message}`);
    }
  }

  // ---- Page open / edit lifecycle ----

  async #openPage(pageId, { published = false } = {}) {
    if (pageId !== this.#pageId && !this.#confirmDiscard()) return;
    this.#pageId = pageId;
    this.#pageVariant = published ? 'published' : 'draft';
    this.#shadow
      .querySelectorAll('.xd-admin-tree button.page')
      .forEach((b) =>
        b.classList.toggle(
          'active',
          b.dataset.page === pageId &&
            (b.dataset.variant === this.#pageVariant || b.dataset.variant === 'single')
        )
      );
    try {
      const tr = await this.#api(`/admin/pages/${pageId}/translations/${this.#editLocale}`);
      this.#revision = tr.revision;
      this.#pageStatus = tr.status;
      this.#translationStatus = tr.translation_status;
      this.#hasDraft = !!tr.has_draft;
      // The Published row shows the live snapshot, read-only; the Draft row is editable.
      const content = published ? (tr.published_markdown ?? tr.markdown) : tr.markdown;
      this.#setReadOnly(published);
      this.#el('.xd-title-input').value = tr.title;
      this.#editor().value = content;
      this.#setDirty(false);
      this.#updateCounts();
      this.#preview(content);
      if (!this.#el('.xd-revs-panel').hidden) this.#loadRevisions();
      this.#status(
        published
          ? 'published version (read-only) — open the Draft row to edit'
          : `rev ${tr.revision} · ${tr.status}${tr.has_draft ? ' · draft' : ''} · ${tr.translation_status}`
      );
    } catch (err) {
      if (err.status === 404) {
        // No translation in this locale yet — offer an LLM-assisted draft.
        this.#revision = null;
        this.#pageStatus = 'draft';
        this.#setReadOnly(false);
        this.#editor().value = '';
        this.#el('.xd-preview').innerHTML = '';
        this.#previewBlocks = [];
        this.#setDirty(false);
        this.#updateCounts();
        this.#status(`No “${this.#editLocale}” translation — use Translate draft (LLM)`);
      } else {
        this.#status(`Error: ${err.message}`);
      }
    }
  }

  /** Toggle the read-only "Published version" view (textarea + save/publish off). */
  #setReadOnly(on) {
    this.#editor().readOnly = on;
    this.#el('.xd-admin').dataset.readonly = String(on);
    this.#el('.xd-save').disabled = on;
    this.#el('.xd-publish').disabled = on;
  }

  async #preview(markdown) {
    try {
      const { html } = await this.#api('/admin/preview', {
        method: 'POST',
        body: JSON.stringify({ markdown }),
      });
      this.#el('.xd-preview').innerHTML = html; // server-sanitized
      this.#indexPreviewBlocks(); // refresh the line→block map used by sync
    } catch {
      /* ignore preview errors */
    }
  }

  async #save() {
    if (!this.#pageId) return;
    const markdown = this.#editor().value;
    const title = this.#el('.xd-title-input').value;
    try {
      const res = await this.#api(`/admin/pages/${this.#pageId}/translations/${this.#editLocale}`, {
        method: 'PUT',
        body: JSON.stringify({ markdown, title, base_revision: this.#revision }),
      });
      this.#revision = res.revision;
      this.#setDirty(false);
      this.#el('.xd-saved').textContent = `saved ${new Date().toLocaleTimeString()}`;
      this.#status(`saved · rev ${res.revision}`);
      if (!this.#el('.xd-revs-panel').hidden) this.#loadRevisions();
    } catch (err) {
      this.#status(err.status === 409 ? 'Conflict: reload the page' : `Error: ${err.message}`);
    }
  }

  async #publish() {
    if (!this.#pageId) return;
    if (this.#dirty) await this.#save(); // publish the latest editor content
    try {
      await this.#api(`/admin/pages/${this.#pageId}/publish`, { method: 'POST' });
      this.#pageStatus = 'published';
      this.#hasDraft = false;
      this.#updateBadge();
      this.#status('published — the draft replaced the live version');
      await this.#loadTree(); // the Published + Draft rows merge back into one
      if (this.#pageId) await this.#openPage(this.#pageId); // reflect the merged state
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #discardDraft() {
    if (!this.#pageId || !this.#hasDraft) {
      this.#status('No draft to discard.');
      return;
    }
    if (!this.#confirm('Discard the draft and revert to the published version?')) return;
    try {
      await this.#api(
        `/admin/pages/${this.#pageId}/discard-draft?locale=${this.#editLocale}`,
        { method: 'POST' }
      );
      this.#hasDraft = false;
      this.#status('draft discarded — reverted to the published version');
      await this.#loadTree();
      if (this.#pageId) await this.#openPage(this.#pageId);
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #unpublish() {
    if (!this.#pageId) return;
    try {
      await this.#api(`/admin/pages/${this.#pageId}/unpublish`, { method: 'POST' });
      this.#pageStatus = 'draft';
      this.#updateBadge();
      this.#status('unpublished (now a draft)');
      this.#loadTree();
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #deletePage() {
    if (!this.#pageId) return;
    const ok = (() => {
      try {
        return window.confirm('Delete this page and all its content? This cannot be undone.');
      } catch {
        return true;
      }
    })();
    if (!ok) return;
    try {
      await this.#api(`/admin/pages/${this.#pageId}`, { method: 'DELETE' });
      this.#pageId = null;
      this.#editor().value = '';
      this.#el('.xd-title-input').value = '';
      this.#el('.xd-preview').innerHTML = '';
      this.#previewBlocks = [];
      this.#setDirty(false);
      this.#updateBadge();
      this.#status('page deleted');
      this.#loadTree();
    } catch (err) {
      this.#status(`Error: ${err.message}`);
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
      this.#translationStatus = res.translation_status;
      this.#status(`status: ${res.translation_status}`);
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  // ---- Revision history ----

  async #loadRevisions() {
    if (!this.#pageId) return;
    const box = this.#el('.xd-revs');
    try {
      const { items } = await this.#api(
        `/admin/pages/${this.#pageId}/revisions?locale=${this.#editLocale}`
      );
      box.replaceChildren();
      if (!items.length) {
        box.innerHTML = '<p class="xd-muted">No revisions yet.</p>';
        return;
      }
      for (const r of items) {
        const row = document.createElement('div');
        row.className = 'xd-rev-row';
        const open = document.createElement('button');
        open.className = 'xd-rev-open';
        const when = r.created_at ? new Date(r.created_at).toLocaleString() : '';
        open.textContent = `rev ${r.revision}${when ? ` · ${when}` : ''}`;
        open.title = 'Preview this revision';
        open.addEventListener('click', () => this.#previewRevision(r.revision));
        const restore = document.createElement('button');
        restore.className = 'xd-rev-restore';
        restore.textContent = 'Restore';
        restore.addEventListener('click', () => this.#restore(r.revision));
        row.append(open, restore);
        box.appendChild(row);
      }
    } catch {
      /* ignore */
    }
  }

  async #previewRevision(revision) {
    try {
      const rev = await this.#api(
        `/admin/pages/${this.#pageId}/revisions/${revision}?locale=${this.#editLocale}`
      );
      this.#setView('preview');
      this.#preview(rev.markdown);
      this.#status(`previewing rev ${revision} (read-only)`);
    } catch (err) {
      this.#status(`Error: ${err.message}`);
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
      this.#setView('split');
      this.#status(`restored rev ${revision}`);
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  // ---- New page ----

  async #newPage(bookId, sectionId = null) {
    const title = this.#prompt('New page title');
    if (!title) return;
    try {
      const page = await this.#api('/admin/pages', {
        method: 'POST',
        body: JSON.stringify({
          book_id: bookId,
          section_id: sectionId,
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

  // ---- Side-menu structure: sections, books, page rename/delete ----

  #prompt(message, value = '') {
    try {
      return window.prompt?.(message, value) || null;
    } catch {
      return null;
    }
  }

  #confirm(message) {
    try {
      return window.confirm(message);
    } catch {
      return true;
    }
  }

  async #newSection(bookId) {
    const title = this.#prompt('New section title');
    if (!title) return;
    try {
      await this.#api('/admin/sections', {
        method: 'POST',
        body: JSON.stringify({ book_id: bookId, title }),
      });
      await this.#loadTree();
      this.#status('section added');
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #renameSection(sec) {
    const title = this.#prompt('Rename section', sec.title);
    if (!title || title === sec.title) return;
    try {
      await this.#api(`/admin/sections/${sec.id}`, {
        method: 'PUT',
        body: JSON.stringify({ title }),
      });
      await this.#loadTree();
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #deleteSection(sectionId) {
    if (!this.#confirm('Delete this section? Its pages are kept and moved to the book root.')) return;
    try {
      await this.#api(`/admin/sections/${sectionId}`, { method: 'DELETE' });
      await this.#loadTree();
      this.#status('section deleted');
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #renameBook(book) {
    const title = this.#prompt('Rename book', book.title);
    if (!title || title === book.title) return;
    try {
      await this.#api(`/admin/books/${book.id}`, {
        method: 'PUT',
        body: JSON.stringify({ title }),
      });
      await this.#refresh(); // reload whichever screen (books grid or editor) is active
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #deleteBook(bookId) {
    if (!this.#confirm('Delete this book and all its pages? This cannot be undone.')) return;
    try {
      await this.#api(`/admin/books/${bookId}`, { method: 'DELETE' });
      // If the open book was deleted, drop back to the books list.
      if (this.#mode === 'editor' && this.#bookId === bookId) {
        this.#gotoBooks();
      } else {
        await this.#refresh();
      }
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #renamePage(p) {
    const title = this.#prompt('Rename page', p.title);
    if (!title || title === p.title) return;
    try {
      await this.#api(`/admin/pages/${p.id}`, {
        method: 'PUT',
        body: JSON.stringify({ title, locale: this.#editLocale }),
      });
      if (p.id === this.#pageId) this.#el('.xd-title-input').value = title;
      await this.#loadTree();
      if (p.id === this.#pageId) {
        this.#shadow
          .querySelectorAll('.xd-admin-tree button.page')
          .forEach((b) => b.classList.toggle('active', b.dataset.page === this.#pageId));
      }
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  async #deletePageById(pageId) {
    if (!this.#confirm('Delete this page and all its content? This cannot be undone.')) return;
    try {
      await this.#api(`/admin/pages/${pageId}`, { method: 'DELETE' });
      if (pageId === this.#pageId) this.#clearEditor();
      await this.#loadTree();
      this.#status('page deleted');
    } catch (err) {
      this.#status(`Error: ${err.message}`);
    }
  }

  /** Reset the editor pane (after the open page is removed from under it). */
  #clearEditor() {
    this.#pageId = null;
    this.#pageVariant = 'single';
    this.#hasDraft = false;
    this.#setReadOnly(false);
    this.#editor().value = '';
    this.#el('.xd-title-input').value = '';
    this.#el('.xd-preview').innerHTML = '';
    this.#previewBlocks = [];
    this.#setDirty(false);
    this.#updateBadge();
  }

  /** Clear the editor if the page it shows no longer exists in the tree. */
  #clearEditorIfDetached() {
    if (
      this.#pageId &&
      !this.#shadow.querySelector(`.xd-admin-tree button.page[data-page="${this.#pageId}"]`)
    ) {
      this.#clearEditor();
    }
  }
}

if (!customElements.get('xdocs-admin')) {
  customElements.define('xdocs-admin', XdocsAdmin);
}

export { XdocsAdmin };
