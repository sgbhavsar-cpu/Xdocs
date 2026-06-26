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

  it('persists drag-reorder via the reorder API (F2)', async () => {
    const el = document.createElement('xdocs-admin');
    el.setAttribute('base-url', 'http://api.test');
    el.setAttribute('space', 'sql-server');
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

    const [p1, p2] = el.shadowRoot.querySelectorAll('.xd-admin-tree button.page');
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
});
