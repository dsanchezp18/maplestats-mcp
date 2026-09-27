# Brand marks

The website's mark is the **pixel leaf** (`icons/pixel-leaf.svg`, the same
file as `site/assets/mark.svg`): a maple leaf built from table cells on a
red tile. The header uses an inline copy in `site/_partials/mark.html`
whose colours follow the light and dark themes.

The other files in `icons/` are the candidates that were considered and
not chosen. They are kept for reference, not used anywhere on the site.

| File | Idea |
| --- | --- |
| `bar-leaf.svg` | A bar chart that peaks like a leaf, on a stem (blue tile). |
| `rising-line.svg`, `rising-line-outlined.svg` | A series that traces a leaf's edge, ending on a data point. |
| `monogram-ms-dark.svg`, `monogram-ms-light.svg` | Plain "ms" lettering, no symbol. |
| `serif-monogram-leaf-dark.svg`, `serif-monogram-leaf-light.svg` | "ms" in Source Serif 4 with a small red pixel leaf. |
| `sans-monogram-leaf-dark.svg`, `sans-monogram-leaf-light.svg` | The same in Source Sans 3, heavier. |

The monograms use `<text>`, so they render in the named font only where it
is installed or loaded. Convert the text to outlines before using one as a
favicon or in print.
