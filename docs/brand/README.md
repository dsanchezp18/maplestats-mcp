# Brand marks

**The logo** (`site/assets/logo.svg`) is a
red square with a white pixel maple leaf and the name `maplestats-mcp` set
below it in Source Serif 4 SemiBold. The name is converted to outlines, so
the file looks the same wherever it is shown, with no font to load. The
home page uses an inline copy (`site/_partials/logo.html`) whose colours
follow the light and dark themes.

**The mark** (`site/assets/mark.svg`) is the
same square with the leaf only. It is the browser-tab icon and the header
icon (`site/_partials/mark.html`). Use it below about 64 px, where the name
in the logo is too small to read.

The leaf is drawn by hand on a 17 × 17 grid, modelled on the 11-point maple
leaf: a tall pointed top lobe with two small side points, notches, two side
lobes, two lower points and a stem. `leaf-17x17.txt` holds the grid
(`#` is a filled cell), and the leaf in each SVG above follows it.

Earlier candidates (a 9 × 9 leaf, a bar-chart leaf, a rising line, "ms"
monograms) were removed; they remain in git history before this cleanup.
