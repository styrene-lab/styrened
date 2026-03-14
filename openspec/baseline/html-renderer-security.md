# html-renderer-security

### Requirement: Rich markup in HTML content is escaped before rendering

HTML content fetched from untrusted sources (I2P eepsites, HTTPS pages) may contain
literal Rich markup syntax (`[bold]`, `[@click=...]`, `[/]`, `[red]`). This must be
escaped before `Text.from_markup()` processes the string, so that only links explicitly
constructed by `_postprocess_links()` carry active markup.

#### Scenario: HTML containing literal [@click] is escaped
Given an HTML page with content `<p>[@click=\"evil\"]pwned[/]</p>`
When the page is rendered via `render_html_to_rich()`
Then the output Text object's plain text contains the literal string `[@click=\"evil\"]pwned[/]`
And no Rich action/click handler is attached to that text span

#### Scenario: HTML containing [bold] markup is escaped
Given an HTML page with content `<p>[bold red]injected[/bold red]</p>`
When the page is rendered via `render_html_to_rich()`
Then the output Text object's plain text contains `[bold red]injected[/bold red]`
And no bold/red styling is applied to that text

#### Scenario: Legitimate links still work after escaping
Given an HTML page with `<a href=\"https://example.com\">click here</a>`
When the page is rendered via `render_html_to_rich()`
Then the output contains a `navigate_link('https://example.com')` click action
And the link text shows `▸ click here` with underline #5ac8fa styling

### Requirement: Image markdown syntax is not converted to clickable links

html2text may emit `![alt](url)` for images or `[](url)` for image-wrapped links.
The link post-processor must not convert these to `navigate_link()` actions.

#### Scenario: Image markdown is not converted to a link
Given markdown text `![logo](https://example.com/img.png)`
When `_postprocess_links()` processes it
Then the text is returned unchanged (no `navigate_link` action)

#### Scenario: Empty-label image link is not converted
Given markdown text `[](https://example.com)`
When `_postprocess_links()` processes it
Then the text is returned unchanged

#### Scenario: Normal link adjacent to image is still converted
Given markdown text `![img](https://example.com/img.png) and [click](https://example.com)`
When `_postprocess_links()` processes it
Then only the `[click](https://example.com)` part is converted to a navigate_link action
And the `![img](...)` part is unchanged

## MODIFIED Requirements

### Requirement: Content-type heuristic reduces micron false positives

The heuristic detects micron content by checking for marker characters at line starts.
Single `>` and backtick are too common in non-micron text (email quotes, markdown code).
Definitive-only markers (`#!c=`, `#!md`, `-=-`) are unambiguous.
Ambiguous markers (`>`, backtick) require at least 2 distinct markers in the first 20 lines.

#### Scenario: Email quote starting with > detected as plain text
Given content starting with `> On Tuesday, Bob wrote:\n> This is a quoted email`
And no content_type_header is provided
When `detect_content_type()` is called
Then it returns `ContentKind.PLAIN`

#### Scenario: Code block starting with backtick detected as plain text
Given content `\`\`\`python\nprint(\"hello\")\n\`\`\``
And no content_type_header is provided
When `detect_content_type()` is called
Then it returns `ContentKind.PLAIN`

#### Scenario: Real micron with definitive marker detected correctly
Given content `#!c=3600\n>Page Title\n\nSome text`
And no content_type_header is provided
When `detect_content_type()` is called
Then it returns `ContentKind.MICRON`

#### Scenario: Real micron with multiple distinct markers detected correctly
Given content `>Page Title\n-= Section =-\n\`Literal block\``
And no content_type_header is provided
When `detect_content_type()` is called
Then it returns `ContentKind.MICRON`

#### Scenario: Single > with no other markers is plain text
Given content `>Just a blockquote\n\nNothing else here`
And no content_type_header is provided
When `detect_content_type()` is called
Then it returns `ContentKind.PLAIN`
