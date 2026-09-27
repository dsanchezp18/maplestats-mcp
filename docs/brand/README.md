# Brand marks

**The logo** (`site/assets/logo.svg`, copied to `docs/brand/logo.svg`) is a
red square with a white pixel maple leaf and the name `maplestats-mcp` set
below it in Source Serif 4 SemiBold. The name is converted to outlines, so
the file looks the same wherever it is shown, with no font to load. The
home page uses an inline copy (`site/_partials/logo.html`) whose colours
follow the light and dark themes.

**The mark** (`site/assets/mark.svg`, also `icons/pixel-leaf.svg`) is the
same square with the leaf only. It is the browser-tab icon and the header
icon (`site/_partials/mark.html`). Use it below about 64 px, where the name
in the logo is too small to read.

The leaf is drawn by hand on a 17 × 17 grid, modelled on the 11-point maple
leaf: a tall pointed top lobe with two small side points, notches, two side
lobes, two lower points and a stem. `leaf-17x17.txt` holds the grid
(`#` is a filled cell), and the leaf in each SVG above follows it.

The other files in `icons/` are earlier candidates, kept for reference and
not used anywhere on the site.

| File | Idea |
| --- | --- |
| `pixel-leaf-9x9.svg` | The first pixel leaf, on a 9 × 9 grid with rounded corners. |
| `bar-leaf.svg` | A bar chart that peaks like a leaf, on a stem (blue tile). |
| `rising-line.svg`, `rising-line-outlined.svg` | A series that traces a leaf's edge, ending on a data point. |
| `monogram-ms-dark.svg`, `monogram-ms-light.svg` | Plain "ms" lettering, no symbol. |
| `serif-monogram-leaf-dark.svg`, `serif-monogram-leaf-light.svg` | "ms" in Source Serif 4 with a small red pixel leaf. |
| `sans-monogram-leaf-dark.svg`, `sans-monogram-leaf-light.svg` | The same in Source Sans 3, heavier. |

The monograms use `<text>`, so they render in the named font only where it
is installed or loaded.
