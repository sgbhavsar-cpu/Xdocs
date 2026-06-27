/**
 * Dependency-free HTML → Markdown converter, tuned for clipboard HTML pasted
 * from Microsoft Word, Excel, and web pages (and Google Docs).
 *
 * The editor stores Markdown, so when a user pastes rich content we down-convert
 * it here instead of dropping the formatting to plain text. The goal is a *useful*
 * approximation — headings, bold/italic/strike, links, lists, and tables — not a
 * lossless round-trip. Anything we cannot represent safely (underline, colors,
 * embedded VML/local images) is reduced to its text content.
 *
 * Runs in the browser and under jsdom (vitest); both provide `DOMParser`.
 */

const WS = /[ \t\r\n\f\v ]+/g;

// Elements that introduce their own block (paragraph) break.
const BLOCK = new Set([
  'address', 'article', 'aside', 'blockquote', 'div', 'dl', 'dd', 'dt',
  'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr', 'li',
  'main', 'nav', 'ol', 'p', 'pre', 'section', 'table', 'tbody', 'tfoot',
  'thead', 'tr', 'ul',
]);

const isElement = (n) => n.nodeType === 1;
const isText = (n) => n.nodeType === 3;
const tag = (n) => (n.tagName ? n.tagName.toLowerCase() : '');

/** Convert a clipboard `text/html` string to Markdown ('' if nothing usable). */
export function htmlToMarkdown(html) {
  let doc;
  try {
    doc = new DOMParser().parseFromString(html, 'text/html');
  } catch {
    return '';
  }
  // Strip Office/HTML noise that would otherwise leak into the text.
  doc
    .querySelectorAll('style, script, meta, link, title, head, o\\:p')
    .forEach((n) => n.remove());
  const body = doc.body || doc.documentElement;
  if (!body) return '';
  return blocks(body).join('\n\n').replace(/\n{3,}/g, '\n\n').trim();
}

// --------------------------------------------------------------------------- //
// Block level: returns an array of block strings (joined with blank lines).
// --------------------------------------------------------------------------- //

function blocks(node) {
  const out = [];
  let buf = '';
  const flush = () => {
    const t = buf.replace(/[ \t]+\n/g, '\n').replace(/[ \t]{2,}/g, ' ').trim();
    if (t) out.push(t);
    buf = '';
  };
  node.childNodes.forEach((c) => {
    if (isElement(c) && BLOCK.has(tag(c))) {
      flush();
      out.push(...blockElement(c));
    } else {
      buf += inline(c);
    }
  });
  flush();
  return out;
}

function blockElement(node) {
  const name = tag(node);
  switch (name) {
    case 'h1': case 'h2': case 'h3': case 'h4': case 'h5': case 'h6': {
      const text = inlineChildren(node).replace(WS, ' ').trim();
      return text ? [`${'#'.repeat(Number(name[1]))} ${text}`] : [];
    }
    case 'hr':
      return ['---'];
    case 'ul':
      return [list(node, false)].filter(Boolean);
    case 'ol':
      return [list(node, true)].filter(Boolean);
    case 'pre': {
      const text = node.textContent.replace(/\n+$/, '');
      return text.trim() ? ['```\n' + text + '\n```'] : [];
    }
    case 'blockquote':
      return blocks(node).map((b) => b.split('\n').map((l) => `> ${l}`).join('\n'));
    case 'table':
      return [table(node)].filter(Boolean);
    default:
      // p, div, section, li-as-block, etc.: recurse into child blocks/inlines.
      return blocks(node);
  }
}

// --------------------------------------------------------------------------- //
// Inline level: returns a string.
// --------------------------------------------------------------------------- //

function inlineChildren(node) {
  let out = '';
  node.childNodes.forEach((c) => {
    out += inline(c);
  });
  return out;
}

function inline(node) {
  if (isText(node)) return node.nodeValue.replace(WS, ' ');
  if (!isElement(node)) return '';
  switch (tag(node)) {
    case 'br':
      return '\n';
    case 'strong': case 'b':
      return wrap(inlineChildren(node), '**');
    case 'em': case 'i':
      return wrap(inlineChildren(node), '_');
    case 'del': case 's': case 'strike':
      return wrap(inlineChildren(node), '~~');
    case 'code':
      return wrap(inlineChildren(node), '`');
    case 'a': {
      const text = inlineChildren(node).trim();
      const href = (node.getAttribute('href') || '').trim();
      if (!href || href.startsWith('javascript:')) return text;
      return text ? `[${text}](${href})` : href;
    }
    case 'img':
      return image(node);
    default:
      // span / font / u / sub / sup / etc.: keep text, honoring style-based
      // bold/italic/strike that Word emits instead of <b>/<i> tags.
      return styled(node, inlineChildren(node));
  }
}

/** Wrap non-empty trimmed inner text in a marker, preserving outer spaces. */
function wrap(inner, marker) {
  const text = inner.trim();
  if (!text) return inner.includes(' ') ? ' ' : '';
  const lead = /^\s/.test(inner) ? ' ' : '';
  const tail = /\s$/.test(inner) ? ' ' : '';
  return `${lead}${marker}${text}${marker}${tail}`;
}

/** Apply Word's inline `style="font-weight/​font-style/​text-decoration"`. */
function styled(node, inner) {
  if (!inner.trim()) return inner;
  const style = (node.getAttribute('style') || '').toLowerCase();
  let s = inner;
  if (/text-decoration[^;]*line-through/.test(style)) s = wrap(s, '~~');
  if (/font-style\s*:\s*italic/.test(style)) s = wrap(s, '_');
  if (/font-weight\s*:\s*(bold|bolder|[6-9]00)/.test(style)) s = wrap(s, '**');
  return s;
}

function image(node) {
  const src = (node.getAttribute('src') || '').trim();
  const alt = (node.getAttribute('alt') || '').trim();
  // Only keep web images; Word/Excel embed file:// paths and VML we can't resolve.
  if (!/^https?:\/\//i.test(src)) return '';
  return `![${alt}](${src})`;
}

// --------------------------------------------------------------------------- //
// Lists & tables
// --------------------------------------------------------------------------- //

function list(node, ordered) {
  const items = [];
  let n = 1;
  node.childNodes.forEach((c) => {
    if (!isElement(c) || tag(c) !== 'li') return;
    const marker = ordered ? `${n++}. ` : '- ';
    const pad = ' '.repeat(marker.length);
    const parts = blocks(c);
    const first = parts.shift() || '';
    let item = marker + first.split('\n').join(`\n${pad}`);
    // Nested lists / extra blocks within the item are indented under it.
    for (const b of parts) item += `\n${b.split('\n').map((l) => pad + l).join('\n')}`;
    items.push(item);
  });
  return items.join('\n');
}

function table(node) {
  const rows = [];
  node.querySelectorAll('tr').forEach((tr) => {
    const cells = [];
    tr.querySelectorAll('th, td').forEach((cell) => {
      const text = inlineChildren(cell).replace(/\s+/g, ' ').trim().replace(/\|/g, '\\|');
      cells.push(text || ' ');
    });
    if (cells.length) rows.push(cells);
  });
  if (!rows.length) return '';
  const width = Math.max(...rows.map((r) => r.length));
  const pad = (r) => {
    while (r.length < width) r.push(' ');
    return r;
  };
  const line = (r) => `| ${r.join(' | ')} |`;
  const head = pad(rows[0].slice());
  const sep = head.map(() => '---');
  const body = rows.slice(1).map((r) => pad(r.slice()));
  return [line(head), line(sep), ...body.map(line)].join('\n');
}
