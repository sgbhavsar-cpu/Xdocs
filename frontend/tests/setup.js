/* Polyfills for browser APIs jsdom lacks, so the Web Component runs under tests. */

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

if (typeof globalThis.IntersectionObserver === 'undefined') {
  globalThis.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

if (typeof window.matchMedia === 'undefined') {
  window.matchMedia = () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  });
}

// Constructable stylesheets (jsdom has no real implementation).
if (typeof globalThis.CSSStyleSheet === 'undefined' || !globalThis.CSSStyleSheet.prototype.replaceSync) {
  globalThis.CSSStyleSheet = class {
    replaceSync() {}
    replace() {
      return Promise.resolve();
    }
  };
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}

if (!('adoptedStyleSheets' in ShadowRoot.prototype)) {
  Object.defineProperty(ShadowRoot.prototype, 'adoptedStyleSheets', {
    writable: true,
    configurable: true,
    value: [],
  });
}
