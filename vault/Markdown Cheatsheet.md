# Markdown Cheatsheet

Everything jadeli understands, in one page. Linked from [[Welcome]].

## Text

**bold**, *italic*, ***both***, ~~struck through~~, ==highlighted==, `inline code`.

## Headings

`#` through `######`. They show up in the **Outline** panel on the right.

## Lists

- One
- Two
  - Nested item
  - Another nested item
- Three

1. First
2. Second
3. Third

- [ ] A task that is still open
- [x] A task that is finished

## Quotes and callouts

> A plain blockquote.

> [!warning] Careful
> Callouts use Obsidian-compatible syntax: `> [!note]`, `> [!tip]`, `> [!warning]`.

## Code

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

## Table

| Chapter | Words | Status |
| --- | --- | --- |
| One | 1,240 | draft |
| Two | 860 | draft |
| Three | 0 | planned |

## Links

- Wiki link: [[Welcome]] — resolves by note title, never breaks on rename… well, almost.
- Wiki link with alias: [[Welcome|back to the start]]
- External link: [Markdown guide](https://commonmark.org/help/)

#reference
