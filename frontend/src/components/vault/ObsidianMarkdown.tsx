import type { ReactNode } from 'react'

export interface ObsidianMarkdownProps {
  body: string
  resolveImage?: (name: string) => string | null
  resolveWikilink?: (title: string) => string | null
  onWikilinkClick?: (noteId: string) => void
}

// Ported from static/js/markdown.js — the same hand-rolled subset of
// markdown + Obsidian syntax project notes actually use (not CommonMark).
// Restructured from sequential string-replacement into a single-pass
// tokenizer emitting real React elements: safer (no HTML string to
// mis-escape) and avoids the original's latent ordering bug where a
// later regex pass could match text inside a tag an earlier pass just
// inserted.
const INLINE_RE =
  /!\[\[(?<embedName>[^\]]+)\]\]|!\[(?<imgAlt>[^\]]*)\]\((?<imgSrc>[^)]+)\)|\[\[(?<wikiTarget>[^\]|]+)(?:\|(?<wikiAlias>[^\]]+))?\]\]|\[(?<linkLabel>[^\]]+)\]\((?<linkUrl>https?:\/\/[^)]+)\)|`(?<code>[^`]+)`|\*\*(?<bold>[^*]+)\*\*|(?<!\*)\*(?<italic>[^*\n]+)\*(?!\*)/g

function renderInline(
  text: string,
  opts: {
    resolveImage?: (name: string) => string | null
    resolveWikilink?: (title: string) => string | null
    onWikilinkClick?: (noteId: string) => void
  },
): ReactNode[] {
  const { resolveImage, resolveWikilink, onWikilinkClick } = opts
  const nodes: ReactNode[] = []
  let lastIndex = 0
  let key = 0
  const re = new RegExp(INLINE_RE)

  for (const match of text.matchAll(re)) {
    const index = match.index ?? 0
    if (index > lastIndex) nodes.push(text.slice(lastIndex, index))
    lastIndex = index + match[0].length
    const g = match.groups!

    if (g.embedName !== undefined) {
      const url = resolveImage?.(g.embedName.trim()) ?? null
      nodes.push(
        url ? (
          <img key={key++} src={url} alt={g.embedName.trim()} loading="lazy" />
        ) : (
          <span key={key++}>{`![[${g.embedName}]]`}</span>
        ),
      )
    } else if (g.imgSrc !== undefined) {
      const url = resolveImage?.(g.imgSrc.trim()) || g.imgSrc.trim()
      nodes.push(<img key={key++} src={url} alt={g.imgAlt ?? ''} loading="lazy" />)
    } else if (g.wikiTarget !== undefined) {
      const label = (g.wikiAlias || g.wikiTarget).trim()
      const noteId = resolveWikilink?.(g.wikiTarget.trim()) ?? null
      nodes.push(
        noteId ? (
          <a
            key={key++}
            href="#"
            className="wikilink cursor-pointer text-accent underline decoration-dotted"
            onClick={(e) => {
              e.preventDefault()
              onWikilinkClick?.(noteId)
            }}
          >
            {label}
          </a>
        ) : (
          <span key={key++} title="Not found in this project" className="text-text-faint">
            {label}
          </span>
        ),
      )
    } else if (g.linkUrl !== undefined) {
      nodes.push(
        <a
          key={key++}
          href={g.linkUrl}
          target="_blank"
          rel="noopener"
          className="text-accent underline"
        >
          {g.linkLabel}
        </a>,
      )
    } else if (g.code !== undefined) {
      nodes.push(
        <code key={key++} className="rounded bg-card-alt px-1 py-0.5 font-mono text-[0.9em]">
          {g.code}
        </code>,
      )
    } else if (g.bold !== undefined) {
      nodes.push(<strong key={key++}>{g.bold}</strong>)
    } else if (g.italic !== undefined) {
      nodes.push(<em key={key++}>{g.italic}</em>)
    }
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex))

  return nodes
}

export default function ObsidianMarkdown({
  body,
  resolveImage,
  resolveWikilink,
  onWikilinkClick,
}: ObsidianMarkdownProps) {
  const lines = (body || '').split('\n')
  const blocks: ReactNode[] = []
  let listItems: ReactNode[] = []
  let key = 0
  const opts = { resolveImage, resolveWikilink, onWikilinkClick }

  function flushList() {
    if (listItems.length > 0) {
      blocks.push(<ul key={key++}>{listItems}</ul>)
      listItems = []
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd()
    if (!line.trim()) {
      flushList()
      continue
    }

    const heading = line.match(/^(#{1,3})\s+(.*)$/)
    if (heading) {
      flushList()
      const Tag = `h${heading[1].length}` as 'h1' | 'h2' | 'h3'
      blocks.push(<Tag key={key++}>{renderInline(heading[2], opts)}</Tag>)
      continue
    }

    const listItem = line.match(/^[-*]\s+(.*)$/)
    if (listItem) {
      listItems.push(<li key={key++}>{renderInline(listItem[1], opts)}</li>)
      continue
    }

    flushList()
    blocks.push(<p key={key++}>{renderInline(line, opts)}</p>)
  }
  flushList()

  return <>{blocks}</>
}
