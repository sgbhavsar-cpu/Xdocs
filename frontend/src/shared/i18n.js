/** Minimal UI string localization for the control chrome (G3). */
const STRINGS = {
  en: {
    search: 'Search…',
    ask: '🤖 Ask',
    askTitle: 'Ask the docs',
    onThisPage: 'On this page',
    thisSpace: 'This space',
    everything: 'Everything',
    send: 'Send',
    exportPdf: '⤓ PDF',
    summarize: 'Summarize this page',
    sources: 'Sources',
    noResults: 'No results',
  },
  fr: {
    search: 'Rechercher…',
    ask: '🤖 Demander',
    askTitle: 'Interroger la doc',
    onThisPage: 'Sur cette page',
    thisSpace: 'Cet espace',
    everything: 'Tout',
    send: 'Envoyer',
    exportPdf: '⤓ PDF',
    summarize: 'Résumer cette page',
    sources: 'Sources',
    noResults: 'Aucun résultat',
  },
  de: {
    search: 'Suchen…',
    ask: '🤖 Fragen',
    askTitle: 'Doku fragen',
    onThisPage: 'Auf dieser Seite',
    thisSpace: 'Dieser Bereich',
    everything: 'Alles',
    send: 'Senden',
    exportPdf: '⤓ PDF',
    summarize: 'Diese Seite zusammenfassen',
    sources: 'Quellen',
    noResults: 'Keine Ergebnisse',
  },
};

export function t(locale, key) {
  const lang = (locale || 'en').split('-')[0];
  return (STRINGS[lang] || STRINGS.en)[key] ?? STRINGS.en[key] ?? key;
}
