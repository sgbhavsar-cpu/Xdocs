/**
 * <xdocs-master> — the documentation portal / landing page (B8).
 *
 * Data-driven: fetches the spaces the caller can read and renders a card grid,
 * plus an optional curated hero (host content via the `hero` slot) and a global
 * search box. Emits `xdocs:open-space` when a card is chosen and `xdocs:search`
 * on query submit, so the host can route to a `<xdocs-viewer>`.
 */

import { mountDevPanel } from '../shared/devpanel.js';

// Replaced at build time with the compiled Tailwind stylesheet (build.mjs).
const STYLES = __XDOCS_CSS__;

class XdocsMaster extends HTMLElement {
  static get observedAttributes() {
    return ['base-url', 'locale', 'theme'];
  }

  #shadow;
  #tokenProvider = null;
  #ready = false;

  constructor() {
    super();
    this.#shadow = this.attachShadow({ mode: 'open' });
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(STYLES);
    this.#shadow.adoptedStyleSheets = [sheet];
  }

  set tokenProvider(fn) {
    this.#tokenProvider = fn;
    if (this.#ready) this.#load();
  }
  get tokenProvider() {
    return this.#tokenProvider;
  }

  get baseUrl() {
    return (this.getAttribute('base-url') || '').replace(/\/$/, '');
  }
  get locale() {
    return this.getAttribute('locale') || 'en';
  }

  connectedCallback() {
    this.#applyTheme();
    this.#renderShell();
    // Re-apply properties set by the host before the element upgraded.
    this.#upgradeProperty('tokenProvider');
    this.#ready = true;
    this.dispatchEvent(new CustomEvent('xdocs:ready', { bubbles: true, composed: true }));
    if (this.#tokenProvider) {
      mountDevPanel(this, this.#shadow, {
        fetchSpaces: async () => (await this.#api('/spaces')).items || [],
      });
    }
    this.#load();
  }

  #upgradeProperty(prop) {
    if (Object.prototype.hasOwnProperty.call(this, prop)) {
      const value = this[prop];
      delete this[prop];
      this[prop] = value;
    }
  }

  attributeChangedCallback(name) {
    if (!this.#ready) return;
    if (name === 'theme') this.#applyTheme();
    else this.#load();
  }

  #applyTheme() {
    const theme = this.getAttribute('theme') || 'auto';
    const dark =
      theme === 'dark' ||
      (theme === 'auto' && window.matchMedia?.('(prefers-color-scheme: dark)').matches);
    this.setAttribute('data-theme', dark ? 'dark' : 'light');
  }

  async #api(path) {
    if (!this.#tokenProvider) throw new Error('no tokenProvider configured');
    const token = await this.#tokenProvider();
    const resp = await fetch(`${this.baseUrl}/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  #renderShell() {
    this.#shadow.innerHTML = `
      <div class="xd-master">
        <header class="xd-master-head">
          <slot name="logo"><strong style="color:var(--xdocs-color-primary)">Xdocs</strong></slot>
          <input class="xd-search" aria-label="Search documentation" placeholder="Search all docs…" />
        </header>
        <slot name="hero"></slot>
        <div class="xd-cards" id="cards"><p id="status">Loading…</p></div>
      </div>`;

    this.#shadow.querySelector('.xd-search').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target.value.trim()) {
        this.dispatchEvent(
          new CustomEvent('xdocs:search', {
            bubbles: true,
            composed: true,
            detail: { query: e.target.value.trim(), scope: 'corpus' },
          })
        );
      }
    });
  }

  #status(msg) {
    const s = this.#shadow.getElementById('status');
    if (s) s.textContent = msg;
  }

  async #load() {
    if (!this.baseUrl || !this.#tokenProvider) {
      this.#status('Not configured (set base-url and tokenProvider).');
      return;
    }
    try {
      const data = await this.#api('/spaces');
      this.#renderCards(data.items || []);
    } catch (err) {
      this.#status(`Failed to load spaces: ${err.message}`);
      this.dispatchEvent(
        new CustomEvent('xdocs:error', {
          bubbles: true,
          composed: true,
          detail: { code: 'load_failed', message: err.message },
        })
      );
    }
  }

  #renderCards(spaces) {
    const cards = this.#shadow.getElementById('cards');
    if (!spaces.length) {
      cards.innerHTML = '<p>No documentation available.</p>';
      return;
    }
    cards.innerHTML = spaces
      .map(
        (s) => `
        <button class="xd-card" data-slug="${s.slug}"${
          s.color ? ` style="--xd-space-color:${s.color}"` : ''
        }>
          <span class="xd-card-title">${s.title}</span>
          <span class="xd-card-desc">${s.description || ''}</span>
          <span class="xd-card-meta">${s.visible_versions.length} version(s)</span>
        </button>`
      )
      .join('');

    cards.querySelectorAll('.xd-card').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.dispatchEvent(
          new CustomEvent('xdocs:open-space', {
            bubbles: true,
            composed: true,
            detail: { slug: btn.dataset.slug },
          })
        );
      });
    });
  }
}

if (!customElements.get('xdocs-master')) {
  customElements.define('xdocs-master', XdocsMaster);
}

export { XdocsMaster };
