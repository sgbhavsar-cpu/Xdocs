import { describe, it, expect } from 'vitest';
import { htmlToMarkdown } from '../src/shared/html-md.js';

describe('htmlToMarkdown', () => {
  it('converts headings and paragraphs', () => {
    const md = htmlToMarkdown('<h1>Title</h1><p>First.</p><p>Second.</p>');
    expect(md).toBe('# Title\n\nFirst.\n\nSecond.');
  });

  it('converts inline emphasis from tags', () => {
    expect(htmlToMarkdown('<p>a <b>bold</b> <i>it</i> <s>old</s></p>')).toBe(
      'a **bold** _it_ ~~old~~'
    );
  });

  it('honors Word style-based bold/italic on spans', () => {
    const html =
      '<p><span style="font-weight:700">heavy</span> and ' +
      '<span style="font-style:italic">slanted</span></p>';
    expect(htmlToMarkdown(html)).toBe('**heavy** and _slanted_');
  });

  it('strips Word noise (style/o:p) and keeps text', () => {
    const html =
      '<style>p{mso-x:1}</style><p class="MsoNormal">Hello<o:p></o:p></p>';
    expect(htmlToMarkdown(html)).toBe('Hello');
  });

  it('converts links, dropping empty/javascript hrefs', () => {
    expect(htmlToMarkdown('<p><a href="https://x.io">x</a></p>')).toBe('[x](https://x.io)');
    expect(htmlToMarkdown('<p><a href="javascript:evil()">x</a></p>')).toBe('x');
  });

  it('converts ordered and unordered lists, including nesting', () => {
    const html = '<ul><li>one</li><li>two<ul><li>two-a</li></ul></li></ul>';
    expect(htmlToMarkdown(html)).toBe('- one\n- two\n  - two-a');
    expect(htmlToMarkdown('<ol><li>a</li><li>b</li></ol>')).toBe('1. a\n2. b');
  });

  it('converts an Excel-style table to a GFM table', () => {
    const html =
      '<table><tr><td>Name</td><td>Qty</td></tr>' +
      '<tr><td>Apples</td><td>5</td></tr></table>';
    expect(htmlToMarkdown(html)).toBe(
      '| Name | Qty |\n| --- | --- |\n| Apples | 5 |'
    );
  });

  it('escapes pipes and pads ragged table rows', () => {
    const html = '<table><tr><th>A|B</th><th>C</th></tr><tr><td>x</td></tr></table>';
    expect(htmlToMarkdown(html)).toBe('| A\\|B | C |\n| --- | --- |\n| x |   |');
  });

  it('keeps only web images', () => {
    expect(htmlToMarkdown('<p><img src="https://x.io/a.png" alt="a"></p>')).toBe(
      '![a](https://x.io/a.png)'
    );
    expect(htmlToMarkdown('<p><img src="file:///c:/a.png" alt="a">text</p>')).toBe('text');
  });

  it('returns empty string for content with no usable text', () => {
    expect(htmlToMarkdown('<style>x{}</style>')).toBe('');
    expect(htmlToMarkdown('')).toBe('');
  });
});
