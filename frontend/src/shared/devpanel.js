/**
 * Dev configuration panel (PendingTask: ISDEV=1).
 *
 * A host integrator can open a small, collapsible panel — without writing any
 * code — to configure the embedded control at runtime: pick which space/version
 * it renders, toggle light/dark, and override the theme colours (the documented
 * `--xdocs-color-*` CSS variables) to match their site. The panel also emits a
 * copy-paste CSS snippet (light + dark) so the chosen overrides can be persisted.
 *
 * Activation: the URL carries `?ISDEV=1` (or `?isdev=1`), or the element has an
 * `isdev` attribute. Otherwise this is a no-op, so it is safe to always call.
 */

const COLOR_VARS = [
  ['--xdocs-color-primary', 'Primary'],
  ['--xdocs-color-bg', 'Background'],
  ['--xdocs-color-fg', 'Text'],
  ['--xdocs-color-surface', 'Surface'],
  ['--xdocs-color-border', 'Border'],
  ['--xdocs-color-muted', 'Muted'],
];

// Default token values per theme (mirror shared/styles.css) used to seed inputs.
const DEFAULTS = {
  light: {
    '--xdocs-color-primary': '#0b5cad',
    '--xdocs-color-bg': '#ffffff',
    '--xdocs-color-fg': '#1f2937',
    '--xdocs-color-surface': '#f9fafb',
    '--xdocs-color-border': '#e5e7eb',
    '--xdocs-color-muted': '#6b7280',
  },
  dark: {
    '--xdocs-color-primary': '#60a5fa',
    '--xdocs-color-bg': '#0f172a',
    '--xdocs-color-fg': '#e5e7eb',
    '--xdocs-color-surface': '#111827',
    '--xdocs-color-border': '#1e293b',
    '--xdocs-color-muted': '#94a3b8',
  },
};

export function isDevMode(host) {
  if (host.hasAttribute('isdev')) return true;
  try {
    const q = new URLSearchParams(window.location.search);
    const v = q.get('ISDEV') ?? q.get('isdev');
    return v === '1' || v === 'true';
  } catch {
    return false;
  }
}

/**
 * Mount the dev panel into `shadow` (a no-op unless dev mode is active).
 *
 * @param {HTMLElement} host  the custom element (attributes are set on it)
 * @param {ShadowRoot}  shadow
 * @param {object} opts
 * @param {() => Promise<Array>} [opts.fetchSpaces] resolves [{slug,title,visible_versions}]
 * @param {(detail: {space?:string, version?:string}) => void} [opts.onApply]
 */
export function mountDevPanel(host, shadow, opts = {}) {
  if (!isDevMode(host)) return;
  if (shadow.querySelector('.xd-devpanel-toggle')) return; // mount once

  const currentTheme = () => host.getAttribute('data-theme') || 'light';
  // Per-theme override maps, seeded from the defaults.
  const overrides = { light: {}, dark: {} };

  const toggle = document.createElement('button');
  toggle.className = 'xd-devpanel-toggle';
  toggle.type = 'button';
  toggle.title = 'Xdocs dev configuration (ISDEV)';
  toggle.textContent = '⚙';

  const panel = document.createElement('div');
  panel.className = 'xd-devpanel';
  panel.hidden = true;
  panel.innerHTML = `
    <div class="xd-devpanel-head"><strong>Dev config</strong><span class="xd-bar-spacer"></span><button class="xd-dp-close" type="button" aria-label="Close">✕</button></div>
    <label class="xd-dp-row">Space
      <select class="xd-dp-space"></select>
    </label>
    <label class="xd-dp-row">Version
      <select class="xd-dp-version"></select>
    </label>
    <label class="xd-dp-row">Theme
      <select class="xd-dp-theme"><option value="light">light</option><option value="dark">dark</option></select>
    </label>
    <div class="xd-dp-colors"></div>
    <div class="xd-dp-actions">
      <button class="xd-dp-reset" type="button">Reset colors</button>
      <span class="xd-bar-spacer"></span>
      <button class="xd-dp-copy" type="button">Copy CSS</button>
    </div>
    <textarea class="xd-dp-css" readonly aria-label="CSS override snippet"></textarea>`;

  shadow.appendChild(toggle);
  shadow.appendChild(panel);

  const $ = (s) => panel.querySelector(s);
  toggle.addEventListener('click', () => (panel.hidden = !panel.hidden));
  $('.xd-dp-close').addEventListener('click', () => (panel.hidden = true));

  // ---- Colour inputs ----
  const colorsBox = $('.xd-dp-colors');
  const inputs = {};
  for (const [varName, label] of COLOR_VARS) {
    const row = document.createElement('label');
    row.className = 'xd-dp-row';
    const span = document.createElement('span');
    span.textContent = label;
    const input = document.createElement('input');
    input.type = 'color';
    input.addEventListener('input', () => {
      overrides[currentTheme()][varName] = input.value;
      host.style.setProperty(varName, input.value);
      refreshCss();
    });
    inputs[varName] = input;
    row.append(span, input);
    colorsBox.appendChild(row);
  }

  const seedInputs = () => {
    const theme = currentTheme();
    for (const [varName] of COLOR_VARS) {
      inputs[varName].value = overrides[theme][varName] || DEFAULTS[theme][varName];
    }
  };

  // Re-apply this theme's overrides to the host (inline custom properties cross
  // the shadow boundary), clearing any from the other theme.
  const applyOverrides = () => {
    const theme = currentTheme();
    for (const [varName] of COLOR_VARS) {
      const val = overrides[theme][varName];
      if (val) host.style.setProperty(varName, val);
      else host.style.removeProperty(varName);
    }
  };

  const refreshCss = () => {
    const block = (theme) => {
      const entries = Object.entries(overrides[theme]);
      if (!entries.length) return '';
      const sel = theme === 'dark' ? `${host.localName}[data-theme="dark"]` : host.localName;
      return `${sel} {\n${entries.map(([k, v]) => `  ${k}: ${v};`).join('\n')}\n}\n`;
    };
    $('.xd-dp-css').value = (block('light') + block('dark')).trim();
  };

  $('.xd-dp-theme').value = currentTheme();
  $('.xd-dp-theme').addEventListener('change', (e) => {
    host.setAttribute('theme', e.target.value); // observed → component re-applies theme
    host.setAttribute('data-theme', e.target.value);
    seedInputs();
    applyOverrides();
  });

  $('.xd-dp-reset').addEventListener('click', () => {
    overrides[currentTheme()] = {};
    seedInputs();
    applyOverrides();
    refreshCss();
  });

  $('.xd-dp-copy').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText($('.xd-dp-css').value);
      $('.xd-dp-copy').textContent = 'Copied!';
      setTimeout(() => ($('.xd-dp-copy').textContent = 'Copy CSS'), 1200);
    } catch {
      $('.xd-dp-css').select();
    }
  });

  // ---- Space / version selectors ----
  const spaceSel = $('.xd-dp-space');
  const versionSel = $('.xd-dp-version');
  let spaces = [];

  const fillVersions = (slug) => {
    const sp = spaces.find((s) => s.slug === slug);
    versionSel.replaceChildren();
    for (const v of sp?.visible_versions || []) {
      const o = document.createElement('option');
      o.value = v.label;
      o.textContent = v.label;
      versionSel.appendChild(o);
    }
  };

  spaceSel.addEventListener('change', () => {
    fillVersions(spaceSel.value);
    apply();
  });
  versionSel.addEventListener('change', apply);

  function apply() {
    host.setAttribute('space', spaceSel.value);
    if (versionSel.value) host.setAttribute('version', versionSel.value);
    opts.onApply?.({ space: spaceSel.value, version: versionSel.value });
  }

  if (opts.fetchSpaces) {
    opts
      .fetchSpaces()
      .then((items) => {
        spaces = items || [];
        spaceSel.replaceChildren();
        for (const s of spaces) {
          const o = document.createElement('option');
          o.value = s.slug;
          o.textContent = s.title || s.slug;
          spaceSel.appendChild(o);
        }
        const cur = host.getAttribute('space');
        if (cur && spaces.some((s) => s.slug === cur)) spaceSel.value = cur;
        fillVersions(spaceSel.value);
      })
      .catch(() => {
        spaceSel.innerHTML = '<option>(failed to load)</option>';
      });
  }

  seedInputs();
  refreshCss();
}
