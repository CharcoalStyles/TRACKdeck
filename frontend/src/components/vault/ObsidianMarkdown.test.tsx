import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ObsidianMarkdown from './ObsidianMarkdown'

describe('ObsidianMarkdown', () => {
  it('renders headings h1-h3', () => {
    const { container } = render(<ObsidianMarkdown body={'# One\n## Two\n### Three'} />)
    expect(container.querySelector('h1')?.textContent).toBe('One')
    expect(container.querySelector('h2')?.textContent).toBe('Two')
    expect(container.querySelector('h3')?.textContent).toBe('Three')
  })

  it('renders a bullet list, closing it on a blank line', () => {
    const { container } = render(<ObsidianMarkdown body={'- a\n- b\n\ntext after'} />)
    const items = container.querySelectorAll('ul li')
    expect(items).toHaveLength(2)
    expect(items[0].textContent).toBe('a')
    expect(container.querySelector('p')?.textContent).toBe('text after')
  })

  it('renders bold, italic, and inline code', () => {
    const { container } = render(<ObsidianMarkdown body={'**bold** and *italic* and `code`'} />)
    expect(container.querySelector('strong')?.textContent).toBe('bold')
    expect(container.querySelector('em')?.textContent).toBe('italic')
    expect(container.querySelector('code')?.textContent).toBe('code')
  })

  it('resolves a wikilink and fires onWikilinkClick with the resolved id', () => {
    const onClick = vi.fn()
    render(
      <ObsidianMarkdown
        body="See [[Other Note]] for more."
        resolveWikilink={(title) => (title === 'Other Note' ? 'note-123' : null)}
        onWikilinkClick={onClick}
      />,
    )
    const link = screen.getByText('Other Note')
    fireEvent.click(link)
    expect(onClick).toHaveBeenCalledWith('note-123')
  })

  it('renders an unresolved wikilink as plain text, not a link', () => {
    const { container } = render(
      <ObsidianMarkdown body="See [[Missing Note]]." resolveWikilink={() => null} />,
    )
    expect(container.querySelector('a.wikilink')).toBeNull()
    expect(container.textContent).toContain('Missing Note')
  })

  it('supports a wikilink alias via the pipe syntax', () => {
    render(
      <ObsidianMarkdown
        body="[[Real Title|Display Text]]"
        resolveWikilink={() => 'id-1'}
      />,
    )
    expect(screen.getByText('Display Text')).toBeTruthy()
  })

  it('resolves an image embed to a servable URL', () => {
    const { container } = render(
      <ObsidianMarkdown
        body="![[photo.png]]"
        resolveImage={(name) => (name === 'photo.png' ? '/attachments/photo.png' : null)}
      />,
    )
    const img = container.querySelector('img')
    expect(img?.getAttribute('src')).toBe('/attachments/photo.png')
  })

  it('leaves an unresolved embed as literal text', () => {
    const { container } = render(<ObsidianMarkdown body="![[missing.png]]" resolveImage={() => null} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toContain('![[missing.png]]')
  })

  it('renders a standard markdown link and image', () => {
    const { container } = render(
      <ObsidianMarkdown body={'[link](https://example.com) and ![alt](https://example.com/x.png)'} />,
    )
    const a = container.querySelector('a')
    expect(a?.getAttribute('href')).toBe('https://example.com')
    expect(a?.textContent).toBe('link')
    const img = container.querySelector('img')
    expect(img?.getAttribute('src')).toBe('https://example.com/x.png')
    expect(img?.getAttribute('alt')).toBe('alt')
  })
})
