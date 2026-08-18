# civic-ui

`civic-ui` is the local Nuxt layer for shared civic-analytics presentation.
It is intentionally small while the first application establishes which
abstractions are truly reusable.

Its first rule is **simpler is better**. Before adding a wrapper, token,
variant, dependency, or configuration option, ask whether the same product
need can be met with less. If it can, use the simpler approach.

The ownership boundary is:

- USWDS supplies component structure, Sass tokens, layout, typography, and
  accessibility guidance.
- This layer supplies the dark Philadelphia theme, Public Sans roles, shared
  site chrome, and content-page composition.
- The application owns gun-violence language, data contracts, routes, maps,
  charts, and page content.

Vue components in this layer should keep official `.usa-*` structure whenever
possible. Add a wrapper only when Vue state, routing, or lifecycle behavior is
useful. Do not recreate a parallel component library that merely resembles
USWDS.

Shared components currently include:

- `CivicCheckboxField` for a native checkbox and its visible label.
- `CivicCopyButton` for copying supplied text with accessible success or
  manual-copy feedback and a selection-based fallback.
- `CivicDisclosurePanel` for native disclosure structure and spacing.
- `CivicFileDownloadLink` for a native file link with a download icon and
  visible format and optional size metadata.
- `CivicIcon` for the small set of decorative USWDS icons shared by components.
- `CivicInfoTooltip` for short, accessible field definitions.
- `CivicRangeField` for a labeled, formatted single-value range control.
- `CivicSelectField` for a labeled native select with optional help text.

Their props describe meaning and state, such as `tone`, `density`, and value
formatting. Callers should not pass arbitrary colors, spacing, or pixel sizes;
those remain CSS and token decisions inside the layer. Domain-specific filters,
histograms, maps, download workflows, and charts remain application components.

`CivicInfoTooltip` currently anchors its panel to the nearest positioned
ancestor so a heading or caption can bound the panel without viewport math.
Place it inside a positioned text container; add a placement API only when a
second real layout requires one.
