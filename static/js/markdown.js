// static/js/markdown.js
//
// A small, hand-rolled renderer for the subset of markdown + Obsidian
// syntax project notes actually use — not a CommonMark implementation.
// Wikilinks ([[Note]]) and embeds (![[image.png]]) are Obsidian-specific
// syntax a generic markdown library wouldn't understand anyway, so
// pulling one in wouldn't save the work that actually matters here.

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderInline(text, { resolveImage, resolveWikilink }) {
  let html = escapeHtml(text);

  // ![[image.png]] — Obsidian embed
  html = html.replace(/!\[\[([^\]]+)\]\]/g, (_, name) => {
    const url = resolveImage ? resolveImage(name.trim()) : null;
    return url
      ? `<img src="${escapeHtml(url)}" alt="${escapeHtml(name.trim())}" loading="lazy">`
      : escapeHtml(`![[${name}]]`);
  });

  // ![alt](src) — standard markdown image
  html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => {
    const resolved = resolveImage ? resolveImage(src.trim()) : null;
    const url = resolved || src.trim();
    return `<img src="${escapeHtml(url)}" alt="${escapeHtml(alt)}" loading="lazy">`;
  });

  // [[Note Title]] or [[Note Title|Alias]] — wikilink
  html = html.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, target, alias) => {
    const label = escapeHtml((alias || target).trim());
    const id = resolveWikilink ? resolveWikilink(target.trim()) : null;
    return id
      ? `<a href="#" class="wikilink" data-note-id="${escapeHtml(id)}">${label}</a>`
      : `<span class="wikilink-missing" title="Not found in this project">${label}</span>`;
  });

  // [text](url) — standard external link
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, (_, label, url) =>
    `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(label)}</a>`
  );

  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');

  return html;
}

/**
 * Render a note body to an HTML string (headings, bold/italic, inline
 * code, bullet lists, links, wikilinks, image embeds).
 * @param {string} body
 * @param {{resolveImage?: (name: string) => string|null, resolveWikilink?: (title: string) => string|null}} opts
 *   resolveImage maps an embedded/linked image filename to a servable
 *   URL; resolveWikilink maps a [[Note Title]] target to a note id.
 * @returns {string} HTML — caller is expected to set it via innerHTML.
 */
export function renderMarkdown(body, { resolveImage, resolveWikilink } = {}) {
  const lines = (body || '').split('\n');
  const htmlParts = [];
  let listOpen = false;

  function closeList() {
    if (listOpen) {
      htmlParts.push('</ul>');
      listOpen = false;
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (!line.trim()) {
      closeList();
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      htmlParts.push(`<h${level}>${renderInline(heading[2], { resolveImage, resolveWikilink })}</h${level}>`);
      continue;
    }

    const listItem = line.match(/^[-*]\s+(.*)$/);
    if (listItem) {
      if (!listOpen) {
        htmlParts.push('<ul>');
        listOpen = true;
      }
      htmlParts.push(`<li>${renderInline(listItem[1], { resolveImage, resolveWikilink })}</li>`);
      continue;
    }

    closeList();
    htmlParts.push(`<p>${renderInline(line, { resolveImage, resolveWikilink })}</p>`);
  }
  closeList();

  return htmlParts.join('\n');
}
