import { describe, it, expect } from 'vitest';
import { XdocsAdmin } from '../src/admin/index.js';

describe('<xdocs-admin>', () => {
  it('registers and renders the authoring shell (F1)', () => {
    expect(customElements.get('xdocs-admin')).toBe(XdocsAdmin);
    const el = document.createElement('xdocs-admin');
    document.body.appendChild(el);
    expect(el.shadowRoot.querySelector('.xd-admin')).toBeTruthy();
    expect(el.shadowRoot.querySelector('.xd-editor')).toBeTruthy();
    expect(el.shadowRoot.querySelector('.xd-publish')).toBeTruthy();
    el.remove();
  });

  it('loads the tree, opens a page, previews, and saves (F1/F3)', async () => {
    const el = document.createElement('xdocs-admin');
    el.setAttribute('base-url', 'http://api.test');
    el.setAttribute('space', 'sql-server');
    el.openPageId = 'p1'; // deep-link straight into the editor (reader → edit flow)
    const calls = [];
    globalThis.fetch = async (url, opts = {}) => {
      calls.push({ url, method: opts.method || 'GET' });
      let body = {};
      if (url.includes('/admin/spaces/') && url.endsWith('/tree')) {
        body = {
          space: 'sql-server',
          books: [
            {
              id: 'b1',
              slug: 'guide',
              title: 'Guide',
              pages: [{ id: 'p1', slug: 'gs', title: 'GS', status: 'draft', parent_page_id: null }],
            },
          ],
        };
      } else if (url.includes('/translations/') && (opts.method || 'GET') === 'GET') {
        body = {
          page_id: 'p1',
          locale: 'en',
          title: 'GS',
          markdown: '# GS',
          revision: 1,
          status: 'draft',
        };
      } else if (url.includes('/admin/preview')) {
        body = { html: '<h1 id="gs">GS</h1>', headings: [] };
      } else if (url.includes('/translations/') && opts.method === 'PUT') {
        body = { page_id: 'p1', locale: 'en', revision: 2, status: 'draft' };
      } else if (url.includes('/revisions')) {
        body = { items: [{ revision: 1 }] };
      }
      return { ok: true, status: 200, json: async () => body };
    };
    el.tokenProvider = async () => 'tok';
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 40));

    // Tree rendered with a draft badge.
    const pageBtn = el.shadowRoot.querySelector('.xd-admin-tree button.page');
    expect(pageBtn).toBeTruthy();
    expect(el.shadowRoot.querySelector('.xd-badge.draft')).toBeTruthy();

    // Open the page -> editor populated + preview rendered.
    pageBtn.click();
    await new Promise((r) => setTimeout(r, 40));
    expect(el.shadowRoot.querySelector('.xd-editor').value).toBe('# GS');
    expect(el.shadowRoot.querySelector('.xd-preview').innerHTML).toContain('GS');

    // Save -> PUT with base_revision, status updates.
    el.shadowRoot.querySelector('.xd-save').click();
    await new Promise((r) => setTimeout(r, 40));
    const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/translations/'));
    expect(put).toBeTruthy();
    expect(el.shadowRoot.querySelector('.xd-admin-status').textContent).toContain('rev 2');
    el.remove();
  });

  it('markdown toolbar wraps the selection (F1 editor)', () => {
    const el = document.createElement('xdocs-admin');
    document.body.appendChild(el);
    const ed = el.shadowRoot.querySelector('.xd-editor');
    ed.value = 'hello world';
    ed.selectionStart = 0;
    ed.selectionEnd = 5;
    el.shadowRoot.querySelector('button[data-md="bold"]').click();
    expect(ed.value).toBe('**hello** world');
    el.remove();
  });

  it('inserts a code block tagged with the selected language', () => {
    const el = document.createElement('xdocs-admin');
    document.body.appendChild(el);
    el.shadowRoot.querySelector('.xd-code-lang').value = 'python';
    const ed = el.shadowRoot.querySelector('.xd-editor');
    ed.value = '';
    ed.selectionStart = ed.selectionEnd = 0;
    el.shadowRoot.querySelector('button[data-md="codeblock"]').click();
    expect(ed.value).toContain('```python');
    el.remove();
  });

  it('dragging the splitter resizes the sidebar and persists it', () => {
    const el = document.createElement('xdocs-admin');
    document.body.appendChild(el);
    const splitter = el.shadowRoot.querySelector('.xd-splitter');
    const admin = el.shadowRoot.querySelector('.xd-admin');
    splitter.dispatchEvent(new Event('pointerdown'));
    const move = new Event('pointermove');
    move.clientX = 300;
    document.dispatchEvent(move);
    expect(admin.style.getPropertyValue('--xd-tree-w')).toBe('300px');
    document.dispatchEvent(new Event('pointerup'));
    expect(localStorage.getItem('xdocs-tree-w')).toBe('300px');
    el.remove();
  });

  it('persists drag-reorder via the reorder API (F2)', async () => {
    const el = document.createElement('xdocs-admin');
    el.setAttribute('base-url', 'http://api.test');
    el.setAttribute('space', 'sql-server');
    el.openPageId = 'p1'; // jump into the editor
    let reorderBody = null;
    globalThis.fetch = async (url, opts = {}) => {
      if (url.includes('/admin/spaces/') && url.endsWith('/tree')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            space: 'sql-server',
            books: [
              {
                id: 'b1',
                slug: 'guide',
                title: 'Guide',
                pages: [
                  { id: 'p1', slug: 'a', title: 'A', status: 'draft', parent_page_id: null },
                  { id: 'p2', slug: 'b', title: 'B', status: 'draft', parent_page_id: null },
                ],
              },
            ],
          }),
        };
      }
      if (url.includes('/admin/pages/reorder')) {
        reorderBody = JSON.parse(opts.body);
        return { ok: true, status: 204, json: async () => null };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    };
    el.tokenProvider = async () => 'tok';
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 40));

    const [p1, p2] = el.shadowRoot.querySelectorAll('.xd-admin-tree .xd-page-row');
    // Simulate dropping p2 before p1.
    const dt = {
      data: {},
      setData(k, v) {
        this.data[k] = v;
      },
      getData(k) {
        return this.data[k];
      },
    };
    p2.dispatchEvent(Object.assign(new Event('dragstart'), { dataTransfer: dt }));
    p1.dispatchEvent(Object.assign(new Event('drop'), { dataTransfer: dt, preventDefault() {} }));
    await new Promise((r) => setTimeout(r, 30));

    expect(reorderBody).toBeTruthy();
    expect(reorderBody.items.map((i) => i.id)).toEqual(['p2', 'p1']);
    el.remove();
  });

  it('generates an LLM translation draft for a new locale (G4)', async () => {
    const el = document.createElement('xdocs-admin');
    el.setAttribute('base-url', 'http://api.test');
    el.setAttribute('space', 'sql-server');
    el.setAttribute('locales', 'en,fr');
    el.openPageId = 'p1'; // jump into the editor
    let frExists = false;
    globalThis.fetch = async (url, opts = {}) => {
      const method = opts.method || 'GET';
      let status = 200;
      let body = {};
      if (url.includes('/admin/spaces/') && url.endsWith('/tree')) {
        body = {
          space: 'sql-server',
          books: [
            {
              id: 'b1',
              slug: 'guide',
              title: 'Guide',
              pages: [{ id: 'p1', slug: 'gs', title: 'GS', status: 'draft', parent_page_id: null }],
            },
          ],
        };
      } else if (url.includes('/translations/en') && method === 'GET') {
        body = {
          page_id: 'p1',
          locale: 'en',
          title: 'GS',
          markdown: '# GS',
          revision: 1,
          status: 'draft',
          translation_status: 'human',
        };
      } else if (url.includes('/translations/fr/draft') && method === 'POST') {
        frExists = true;
        body = { page_id: 'p1', locale: 'fr', revision: 1, translation_status: 'llm_draft' };
      } else if (url.includes('/translations/fr') && method === 'GET') {
        if (!frExists) {
          status = 404;
          body = { error: {} };
        } else {
          body = {
            page_id: 'p1',
            locale: 'fr',
            title: 'GS',
            markdown: '[translated] # GS',
            revision: 1,
            status: 'draft',
            translation_status: 'llm_draft',
          };
        }
      } else if (url.includes('/admin/preview')) body = { html: '<h1>x</h1>', headings: [] };
      else if (url.includes('/revisions')) body = { items: [] };
      return { ok: status < 400, status, json: async () => body };
    };
    el.tokenProvider = async () => 'tok';
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 40));

    el.shadowRoot.querySelector('.xd-admin-tree button.page').click();
    await new Promise((r) => setTimeout(r, 40));

    // Switch to French — no translation yet.
    const lang = el.shadowRoot.querySelector('.xd-admin-lang');
    lang.value = 'fr';
    lang.dispatchEvent(new Event('change'));
    await new Promise((r) => setTimeout(r, 40));
    expect(el.shadowRoot.querySelector('.xd-admin-status').textContent).toContain('No');

    // Generate the LLM draft.
    el.shadowRoot.querySelector('.xd-draft').click();
    await new Promise((r) => setTimeout(r, 60));
    expect(el.shadowRoot.querySelector('.xd-editor').value).toContain('translated');
    el.remove();
  });

  it('renders the spaces grid (no space set) with colour and opens a space', async () => {
    const el = document.createElement('xdocs-admin');
    el.setAttribute('base-url', 'http://api.test');
    globalThis.fetch = async (url) => {
      let body = {};
      if (url.endsWith('/admin/spaces')) {
        body = {
          items: [
            {
              slug: 'sql-server',
              title: 'SQL Server',
              description: 'Docs',
              color: '#16a34a',
              default_locale: 'en',
              book_count: 2,
              page_count: 5,
            },
          ],
        };
      } else if (url.includes('/admin/spaces/sql-server/tree')) {
        body = {
          space: 'sql-server',
          title: 'SQL Server',
          color: '#16a34a',
          books: [{ id: 'b1', slug: 'guide', title: 'Guide', sections: [], pages: [] }],
        };
      }
      return { ok: true, status: 200, json: async () => body };
    };
    el.tokenProvider = async () => 'tok';
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 40));

    // Spaces mode is active (no `space` attribute) with a coloured card.
    const root = el.shadowRoot.querySelector('.xd-admin-root');
    expect(root.dataset.mode).toBe('spaces');
    const card = el.shadowRoot.querySelector('.xd-space-card');
    expect(card).toBeTruthy();
    expect(card.style.getPropertyValue('--xd-space-color')).toBe('#16a34a');

    // Clicking a space drills into its Books screen.
    el.shadowRoot.querySelector('.xd-space-open').click();
    await new Promise((r) => setTimeout(r, 40));
    expect(el.shadowRoot.querySelector('.xd-admin-root').dataset.mode).toBe('books');
    expect(el.getAttribute('space')).toBe('sql-server');
    const bookCard = el.shadowRoot.querySelector('.xd-book-grid .xd-space-open');
    expect(bookCard.textContent).toContain('Guide');

    // Opening a book enters the editor for that book.
    bookCard.click();
    await new Promise((r) => setTimeout(r, 40));
    expect(el.shadowRoot.querySelector('.xd-admin-root').dataset.mode).toBe('editor');
    expect(el.shadowRoot.querySelector('.xd-admin-tree .xd-book-title').textContent).toBe('Guide');
    el.remove();
  });

  it('shows section sub-headers and page rename/delete actions in the sidebar', async () => {
    const el = document.createElement('xdocs-admin');
    el.setAttribute('base-url', 'http://api.test');
    el.setAttribute('space', 'sql-server');
    el.openPageId = 'p1'; // deep-link into the editor for the book holding p1
    const calls = [];
    globalThis.fetch = async (url, opts = {}) => {
      calls.push({ url, method: opts.method || 'GET' });
      let body = {};
      if (url.includes('/admin/spaces/') && url.endsWith('/tree')) {
        body = {
          space: 'sql-server',
          title: 'SQL Server',
          color: '#0b5cad',
          books: [
            {
              id: 'b1',
              slug: 'guide',
              title: 'Guide',
              sections: [
                {
                  id: 's1',
                  title: 'Statements',
                  pages: [
                    { id: 'p1', slug: 'sel', title: 'SELECT', status: 'published', section_id: 's1' },
                  ],
                },
              ],
              pages: [{ id: 'p2', slug: 'intro', title: 'Intro', status: 'draft', section_id: null }],
            },
          ],
        };
      }
      return { ok: true, status: opts.method === 'DELETE' ? 204 : 200, json: async () => body };
    };
    el.tokenProvider = async () => 'tok';
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 40));

    // Section header + both pages rendered.
    expect(el.shadowRoot.querySelector('.xd-section-title').textContent).toBe('Statements');
    expect(el.shadowRoot.querySelectorAll('.xd-page-row').length).toBe(2);
    // Coloured space banner at the top of the tree.
    expect(el.shadowRoot.querySelector('.xd-tree-space')).toBeTruthy();

    // Rename a page -> PUT /admin/pages/{id}.
    globalThis.prompt = () => 'SELECT v2';
    el.shadowRoot.querySelector('.xd-page-row .xd-row-act').click();
    await new Promise((r) => setTimeout(r, 30));
    const put = calls.find((c) => c.method === 'PUT' && /\/admin\/pages\/p1$/.test(c.url));
    expect(put).toBeTruthy();

    // Delete a page -> DELETE /admin/pages/{id}.
    globalThis.confirm = () => true;
    const del = el.shadowRoot.querySelectorAll('.xd-page-row')[0].querySelectorAll('.xd-row-act')[1];
    del.click();
    await new Promise((r) => setTimeout(r, 30));
    expect(calls.find((c) => c.method === 'DELETE' && /\/admin\/pages\/p1$/.test(c.url))).toBeTruthy();
    el.remove();
  });

  it('shows Published + Draft rows for a page with unpublished edits', async () => {
    const el = document.createElement('xdocs-admin');
    el.setAttribute('base-url', 'http://api.test');
    el.setAttribute('space', 'sql-server');
    el.openPageId = 'p1';
    globalThis.fetch = async (url, opts = {}) => {
      const method = opts.method || 'GET';
      let body = {};
      if (url.includes('/admin/spaces/') && url.endsWith('/tree')) {
        body = {
          space: 'sql-server',
          title: 'SQL Server',
          books: [
            {
              id: 'b1',
              slug: 'guide',
              title: 'Guide',
              sections: [],
              pages: [
                {
                  id: 'p1',
                  slug: 'sel',
                  title: 'SELECT',
                  status: 'published',
                  has_draft: true,
                  section_id: null,
                },
              ],
            },
          ],
        };
      } else if (url.includes('/translations/') && method === 'GET') {
        body = {
          page_id: 'p1',
          locale: 'en',
          title: 'SELECT',
          markdown: '# draft body',
          published_markdown: '# published body',
          has_draft: true,
          revision: 3,
          status: 'published',
          translation_status: 'human',
        };
      } else if (url.includes('/admin/preview')) {
        body = { html: '<h1>x</h1>', headings: [] };
      } else if (url.includes('/revisions')) {
        body = { items: [] };
      }
      return { ok: true, status: 200, json: async () => body };
    };
    el.tokenProvider = async () => 'tok';
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 50));

    // Two rows: a Published (read-only) row and a Draft row.
    const rows = [...el.shadowRoot.querySelectorAll('.xd-page-row')];
    expect(rows.map((r) => r.dataset.variant)).toEqual(['published', 'draft']);

    const ed = el.shadowRoot.querySelector('.xd-editor');
    // Opening the Published row shows the live snapshot read-only.
    el.shadowRoot.querySelector('.xd-page-row[data-variant="published"] button.page').click();
    await new Promise((r) => setTimeout(r, 40));
    expect(ed.readOnly).toBe(true);
    expect(ed.value).toBe('# published body');

    // Opening the Draft row is editable and shows the working copy.
    el.shadowRoot.querySelector('.xd-page-row[data-variant="draft"] button.page').click();
    await new Promise((r) => setTimeout(r, 40));
    expect(ed.readOnly).toBe(false);
    expect(ed.value).toBe('# draft body');
    el.remove();
  });

  it('Books screen adds a book and exports a book to zip', async () => {
    const el = document.createElement('xdocs-admin');
    el.setAttribute('base-url', 'http://api.test');
    el.setAttribute('space', 'sql-server');
    const calls = [];
    globalThis.fetch = async (url, opts = {}) => {
      calls.push({ url, method: opts.method || 'GET' });
      let body = {};
      if (url.includes('/admin/spaces/sql-server/tree')) {
        body = {
          space: 'sql-server',
          title: 'SQL Server',
          books: [{ id: 'b1', slug: 'guide', title: 'Guide', sections: [], pages: [] }],
        };
      } else if (/\/admin\/spaces\/sql-server\/books$/.test(url) && opts.method === 'POST') {
        body = { id: 'b2', slug: 'new-book', title: JSON.parse(opts.body).title };
      } else if (/\/admin\/books\/b1\/archive$/.test(url)) {
        return { ok: true, status: 200, blob: async () => new Blob(['zip']) };
      }
      return { ok: true, status: 200, json: async () => body };
    };
    el.tokenProvider = async () => 'tok';
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 40));

    // Books mode shows the book grid.
    expect(el.shadowRoot.querySelector('.xd-admin-root').dataset.mode).toBe('books');
    expect(el.shadowRoot.querySelector('.xd-book-grid .xd-space-open').textContent).toContain(
      'Guide'
    );

    // Export the book -> GET /admin/books/{id}/archive (blob download).
    if (!globalThis.URL.createObjectURL) globalThis.URL.createObjectURL = () => 'blob:x';
    if (!globalThis.URL.revokeObjectURL) globalThis.URL.revokeObjectURL = () => {};
    const exportBtn = [
      ...el.shadowRoot.querySelectorAll('.xd-book-grid .xd-space-actions button'),
    ].find((b) => b.title.includes('Export'));
    exportBtn.click();
    await new Promise((r) => setTimeout(r, 40));
    expect(calls.find((c) => /\/admin\/books\/b1\/archive$/.test(c.url))).toBeTruthy();

    // Add a book -> POST /admin/spaces/{slug}/books.
    globalThis.prompt = () => 'New Book';
    el.shadowRoot.querySelector('.xd-new-book').click();
    await new Promise((r) => setTimeout(r, 40));
    expect(
      calls.find((c) => c.method === 'POST' && /\/admin\/spaces\/sql-server\/books$/.test(c.url))
    ).toBeTruthy();
    el.remove();
  });

  // ---- Word-like editor features ----

  it('toggles bold off when the selection is already bold', () => {
    const el = document.createElement('xdocs-admin');
    document.body.appendChild(el);
    const ed = el.shadowRoot.querySelector('.xd-editor');
    ed.value = '**hello** world';
    ed.selectionStart = 2;
    ed.selectionEnd = 7; // "hello", between the ** markers
    el.shadowRoot.querySelector('button[data-md="bold"]').click();
    expect(ed.value).toBe('hello world');
    el.remove();
  });

  it('replaces all matches via the find & replace bar', () => {
    const el = document.createElement('xdocs-admin');
    document.body.appendChild(el);
    const ed = el.shadowRoot.querySelector('.xd-editor');
    ed.value = 'cat dog cat dog cat';
    ed.selectionStart = ed.selectionEnd = 0;
    el.shadowRoot.querySelector('.xd-find-btn').click();
    el.shadowRoot.querySelector('.xd-find-input').value = 'cat';
    el.shadowRoot.querySelector('.xd-find-input').dispatchEvent(new Event('input'));
    expect(el.shadowRoot.querySelector('.xd-find-count').textContent).toBe('1/3');
    el.shadowRoot.querySelector('.xd-replace-input').value = 'fox';
    el.shadowRoot.querySelector('.xd-replace-all').click();
    expect(ed.value).toBe('fox dog fox dog fox');
    el.remove();
  });

  it('lists document headings in the outline navigator', () => {
    const el = document.createElement('xdocs-admin');
    document.body.appendChild(el);
    const ed = el.shadowRoot.querySelector('.xd-editor');
    ed.value = '# Title\n\n## Setup\n\ntext\n\n## Usage';
    el.shadowRoot.querySelector('.xd-outline-btn').click();
    const items = [...el.shadowRoot.querySelectorAll('.xd-outline-item')];
    expect(items.map((i) => i.textContent)).toEqual(['Title', 'Setup', 'Usage']);
    el.remove();
  });

  it('moves the current line down with Alt+ArrowDown', () => {
    const el = document.createElement('xdocs-admin');
    document.body.appendChild(el);
    const ed = el.shadowRoot.querySelector('.xd-editor');
    ed.value = 'line one\nline two';
    ed.selectionStart = ed.selectionEnd = 0; // on "line one"
    ed.dispatchEvent(
      Object.assign(new Event('keydown'), { key: 'ArrowDown', altKey: true, preventDefault() {} })
    );
    expect(ed.value).toBe('line two\nline one');
    el.remove();
  });

  it('selects the source lines when a preview block is clicked (sync)', async () => {
    const el = document.createElement('xdocs-admin');
    el.setAttribute('base-url', 'http://api.test');
    el.setAttribute('space', 'sql-server');
    el.openPageId = 'p1';
    globalThis.fetch = async (url, opts = {}) => {
      const method = opts.method || 'GET';
      let body = {};
      if (url.includes('/admin/spaces/') && url.endsWith('/tree')) {
        body = {
          space: 'sql-server',
          books: [
            {
              id: 'b1',
              slug: 'guide',
              title: 'Guide',
              pages: [{ id: 'p1', slug: 'gs', title: 'GS', status: 'draft', parent_page_id: null }],
            },
          ],
        };
      } else if (url.includes('/translations/') && method === 'GET') {
        body = {
          page_id: 'p1',
          locale: 'en',
          title: 'GS',
          markdown: '# Title\n\npara one\n\npara two',
          revision: 1,
          status: 'draft',
        };
      } else if (url.includes('/admin/preview')) {
        // Preview HTML carries the data-sl source-line attributes the sync relies on.
        body = {
          html:
            '<h1 data-sl="0" id="title">Title</h1>' +
            '<p data-sl="2">para one</p>' +
            '<p data-sl="4">para two</p>',
          headings: [],
        };
      }
      return { ok: true, status: 200, json: async () => body };
    };
    el.tokenProvider = async () => 'tok';
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 40));
    el.shadowRoot.querySelector('.xd-admin-tree button.page').click();
    await new Promise((r) => setTimeout(r, 60));

    const ed = el.shadowRoot.querySelector('.xd-editor');
    const block = el.shadowRoot.querySelector('.xd-preview p[data-sl="4"]');
    block.dispatchEvent(new Event('click', { bubbles: true }));
    // "para two" is on source line 4 -> offset 19, length 8.
    expect(ed.selectionStart).toBe(19);
    expect(ed.value.slice(ed.selectionStart, ed.selectionEnd)).toBe('para two');
    el.remove();
  });
});
