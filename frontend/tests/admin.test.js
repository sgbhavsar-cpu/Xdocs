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
        body = { page_id: 'p1', locale: 'en', title: 'GS', markdown: '# GS', revision: 1, status: 'draft' };
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
});
