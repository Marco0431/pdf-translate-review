# HTML rendering sample

This synthetic Chinese document demonstrates the existing Markdown-to-HTML renderer with a paragraph, equation, local diagram, and table. The text and diagram were authored for this repository; they are not a real paper or a model translation benchmark. The PNG used by the sample is included alongside its editable SVG source.

From the repository root, install the locked Node.js dependencies and render:

```sh
npm ci --ignore-scripts
python scripts/build_html.py examples/rendering-demo/translation.md rendering-demo.html
node scripts/verify_katex_md.js examples/rendering-demo/translation.md
```

Open `rendering-demo.html` in a browser. The existing build script embeds the diagram and fonts and renders the equation with KaTeX. Remove the generated HTML when finished. Its visual style is separate from the source-aligned review workflow: rendering a document does not establish translation accuracy or complete a semantic review.
