import { describe, it, expect, beforeAll } from 'vitest';
import { XdocsViewer } from '../src/viewer/index.js';

describe('<xdocs-viewer>', () => {
  beforeAll(() => {
    // Importing the module registers the custom element.
    expect(customElements.get('xdocs-viewer')).toBe(XdocsViewer);
  });

  it('mounts a shadow root with the three-pane shell (A-07)', () => {
    const el = document.createElement('xdocs-viewer');
    el.setAttribute('space', 'sql-server');
    document.body.appendChild(el);

    expect(el.shadowRoot).toBeTruthy();
    const text = el.shadowRoot.textContent;
    expect(text).toContain('Documentation');
    expect(el.shadowRoot.querySelector('nav[aria-label="Pages"]')).toBeTruthy();
    expect(el.shadowRoot.querySelector('aside[aria-label="On this page"]')).toBeTruthy();
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
});
