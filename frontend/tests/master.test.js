import { describe, it, expect } from 'vitest';
import { XdocsMaster } from '../src/master/index.js';

describe('<xdocs-master>', () => {
  it('registers and mounts a portal shell (B8)', () => {
    expect(customElements.get('xdocs-master')).toBe(XdocsMaster);
    const el = document.createElement('xdocs-master');
    document.body.appendChild(el);
    expect(el.shadowRoot.querySelector('.xd-master')).toBeTruthy();
    expect(el.shadowRoot.querySelector('input[aria-label="Search documentation"]')).toBeTruthy();
    el.remove();
  });

  it('shows "not configured" without base-url/tokenProvider', () => {
    const el = document.createElement('xdocs-master');
    document.body.appendChild(el);
    expect(el.shadowRoot.getElementById('status').textContent).toContain('Not configured');
    el.remove();
  });

  it('renders space cards from the API and emits open-space (B8)', async () => {
    const el = document.createElement('xdocs-master');
    el.setAttribute('base-url', 'http://api.test');
    globalThis.fetch = async () => ({
      ok: true,
      json: async () => ({
        items: [
          {
            slug: 'sql-server',
            title: 'SQL Server',
            description: 'Demo',
            visible_versions: [{ label: '2022' }, { label: '2019' }],
          },
        ],
      }),
    });
    el.tokenProvider = async () => 'demo-token';
    document.body.appendChild(el);

    // Let the async #load() settle.
    await new Promise((r) => setTimeout(r, 0));

    const card = el.shadowRoot.querySelector('.xd-card[data-slug="sql-server"]');
    expect(card).toBeTruthy();
    expect(card.textContent).toContain('2 version(s)');

    const opened = new Promise((resolve) => el.addEventListener('xdocs:open-space', resolve));
    card.click();
    const evt = await opened;
    expect(evt.detail.slug).toBe('sql-server');
    el.remove();
  });

  it('emits xdocs:search on Enter', async () => {
    const el = document.createElement('xdocs-master');
    document.body.appendChild(el);
    const input = el.shadowRoot.querySelector('input[aria-label="Search documentation"]');
    input.value = 'select into';
    const search = new Promise((resolve) => el.addEventListener('xdocs:search', resolve));
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    const evt = await search;
    expect(evt.detail.query).toBe('select into');
    expect(evt.detail.scope).toBe('corpus');
    el.remove();
  });
});
