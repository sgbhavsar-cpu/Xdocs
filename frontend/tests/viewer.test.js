import { describe, it, expect, beforeAll } from 'vitest';
import { XdocsViewer } from '../src/viewer/index.js';

describe('<xdocs-viewer>', () => {
  beforeAll(() => {
    // Importing the module registers the custom element.
    expect(customElements.get('xdocs-viewer')).toBe(XdocsViewer);
  });

  it('mounts a shadow root with the three-pane shell (A-07/B-04)', () => {
    const el = document.createElement('xdocs-viewer');
    el.setAttribute('space', 'sql-server');
    document.body.appendChild(el);

    expect(el.shadowRoot).toBeTruthy();
    expect(el.shadowRoot.querySelector('.xd-root')).toBeTruthy();
    expect(el.shadowRoot.querySelector('nav[aria-label="Pages"]')).toBeTruthy();
    expect(el.shadowRoot.querySelector('aside[aria-label="On this page"]')).toBeTruthy();
    expect(el.shadowRoot.querySelector('input[aria-label="Search"]')).toBeTruthy();
    expect(el.shadowRoot.querySelector('.xd-hamburger')).toBeTruthy();
    el.remove();
  });

  it('toggles the mobile nav drawer via the hamburger', () => {
    const el = document.createElement('xdocs-viewer');
    document.body.appendChild(el);
    const root = el.shadowRoot.querySelector('.xd-root');
    expect(root.dataset.navOpen).toBe('false');
    el.shadowRoot.querySelector('.xd-hamburger').click();
    expect(root.dataset.navOpen).toBe('true');
    el.remove();
  });

  it('toggles the bottom-sheet TOC via the FAB (B6)', () => {
    const el = document.createElement('xdocs-viewer');
    document.body.appendChild(el);
    const sheet = el.shadowRoot.querySelector('.xd-sheet');
    expect(sheet.dataset.open).toBe('false');
    el.shadowRoot.querySelector('.xd-toc-fab').click();
    expect(sheet.dataset.open).toBe('true');
    el.remove();
  });

  it('emits xdocs:ready on connect', async () => {
    const el = document.createElement('xdocs-viewer');
    const ready = new Promise((resolve) => el.addEventListener('xdocs:ready', resolve));
    document.body.appendChild(el);
    const evt = await ready;
    expect(evt.detail.version).toBe('0.0.1');
    el.remove();
  });

  it('applies dark theme attribute', () => {
    const el = document.createElement('xdocs-viewer');
    el.setAttribute('theme', 'dark');
    document.body.appendChild(el);
    expect(el.getAttribute('data-theme')).toBe('dark');
    el.remove();
  });

  it('shows "not configured" when base-url/tokenProvider are absent', () => {
    const el = document.createElement('xdocs-viewer');
    document.body.appendChild(el);
    const status = el.shadowRoot.getElementById('status');
    expect(status.textContent).toContain('Not configured');
    el.remove();
  });

  it('renders search results and deep-links on click (C4/C5)', async () => {
    const el = document.createElement('xdocs-viewer');
    el.setAttribute('base-url', 'http://api.test');
    el.setAttribute('space', 'sql-server');
    globalThis.fetch = async (url) => {
      let body = {};
      if (url.includes('/search')) {
        body = {
          results: [
            {
              page_id: 'p1',
              title: 'SELECT INTO',
              space: 'sql-server',
              book_id: 'b1',
              locale: 'en',
              best_anchor: 'creating-a-table',
              snippet: 'use <em>select</em> into',
            },
          ],
        };
      } else if (url.includes('/me')) body = { sub: 'u' };
      else if (url.includes('/tree')) body = { books: [] };
      else if (url.includes('/pages/')) {
        body = {
          id: 'p1',
          slug: 'select-into',
          title: 'SELECT INTO',
          space: 'sql-server',
          book: 't-sql',
          version: { label: '2022' },
          locale: 'en',
          translation_status: 'human',
          html: '<h1 id="select-into">SELECT INTO</h1><h2 id="creating-a-table">Creating a table</h2>',
          headings: [{ level: 2, id: 'creating-a-table', text: 'Creating a table' }],
          available_locales: ['en'],
          fallback: null,
        };
      }
      return { ok: true, json: async () => body };
    };
    el.tokenProvider = async () => 'tok';
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 50));

    const input = el.shadowRoot.querySelector('.xd-search');
    input.value = 'select';
    input.dispatchEvent(new Event('input'));
    await new Promise((r) => setTimeout(r, 300)); // debounce + fetch

    const results = el.shadowRoot.querySelectorAll('.xd-result');
    expect(results.length).toBe(1);
    expect(el.shadowRoot.querySelector('.xd-result-title').textContent).toBe('SELECT INTO');
    expect(el.shadowRoot.querySelector('.xd-result-snip').innerHTML).toContain('<em>');

    results[0].click();
    await new Promise((r) => setTimeout(r, 50));
    expect(el.shadowRoot.getElementById('content').textContent).toContain('Creating a table');
    el.remove();
  });

  it('exports the current page as PDF (E3)', async () => {
    const el = document.createElement('xdocs-viewer');
    el.setAttribute('base-url', 'http://api.test');
    el.setAttribute('space', 'sql-server');
    const calls = [];
    globalThis.fetch = async (url) => {
      calls.push(url);
      if (url.endsWith('/api/v1/export')) {
        return {
          ok: true,
          json: async () => ({
            job_id: 'j1',
            status: 'done',
            url: '/api/v1/export/j1/download',
            page_count: 1,
            expires_at: '2099-01-01T00:00:00Z',
            error: null,
          }),
        };
      }
      if (url.includes('/download')) return { ok: true, blob: async () => new Blob(['%PDF']) };
      let body = {};
      if (url.includes('/me')) body = { sub: 'u' };
      else if (url.includes('/tree')) {
        body = {
          books: [
            {
              id: 'b1',
              slug: 'guide',
              title: 'Guide',
              pages: [{ id: 'p1', slug: 'gs', title: 'GS', has_children: false, children: [] }],
            },
          ],
        };
      } else if (url.includes('/pages/')) {
        body = {
          id: 'p1',
          slug: 'gs',
          title: 'GS',
          space: 'sql-server',
          book: 'guide',
          version: { label: '1' },
          locale: 'en',
          translation_status: 'human',
          html: '<h1 id="gs">GS</h1>',
          headings: [],
          available_locales: ['en'],
          fallback: null,
        };
      }
      return { ok: true, json: async () => body };
    };
    el.tokenProvider = async () => 'tok';
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 80));

    el.shadowRoot.querySelector('.xd-export-btn').click();
    await new Promise((r) => setTimeout(r, 60));
    expect(calls.some((u) => u.endsWith('/api/v1/export'))).toBe(true);
    expect(calls.some((u) => u.includes('/download'))).toBe(true);
    el.remove();
  });

  it('opens the Ask panel (D3)', () => {
    const el = document.createElement('xdocs-viewer');
    document.body.appendChild(el);
    const ask = el.shadowRoot.querySelector('.xd-ask');
    expect(ask.dataset.open).toBe('false');
    el.shadowRoot.querySelector('.xd-ask-btn').click();
    expect(ask.dataset.open).toBe('true');
    el.remove();
  });

  it('summarizes the current page into the Ask panel (D4)', async () => {
    const el = document.createElement('xdocs-viewer');
    el.setAttribute('base-url', 'http://api.test');
    el.setAttribute('space', 'sql-server');
    globalThis.fetch = async (url) => {
      let body = {};
      if (url.includes('/me')) body = { sub: 'u' };
      else if (url.includes('/tree')) {
        body = {
          books: [
            {
              id: 'b1',
              slug: 'guide',
              title: 'Guide',
              pages: [{ id: 'p1', slug: 'gs', title: 'GS', has_children: false, children: [] }],
            },
          ],
        };
      } else if (url.includes('/pages/')) {
        body = {
          id: 'p1',
          slug: 'gs',
          title: 'GS',
          space: 'sql-server',
          book: 'guide',
          version: { label: '1' },
          locale: 'en',
          translation_status: 'human',
          html: '<h1 id="gs">GS</h1>',
          headings: [],
          available_locales: ['en'],
          fallback: null,
        };
      } else if (url.includes('/summarize')) {
        body = {
          artifact_id: 'a1',
          kind: 'summary',
          markdown: '## Summary\n\nhello',
          download: { md: '/x' },
          expires_at: '2099-01-01T00:00:00Z',
        };
      }
      return { ok: true, json: async () => body };
    };
    el.tokenProvider = async () => 'tok';
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 80)); // load first page -> currentPageId

    el.shadowRoot.querySelector('.xd-ask-btn').click();
    el.shadowRoot.querySelector('.xd-ask-summary').click();
    await new Promise((r) => setTimeout(r, 60));
    expect(el.shadowRoot.querySelector('.xd-ask-answer').textContent).toContain('Summary');
    el.remove();
  });
});
