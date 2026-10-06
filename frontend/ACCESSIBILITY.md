# Accessibility standard and verification

The frontend targets **WCAG 2.1 Level AA** across the dashboard and About page,
including loading, error, filtering, map-layer, and download-dialog states.

Automated Playwright checks use axe rules tagged for WCAG 2.0 and 2.1 Level A
and AA. They are regression guards, not a complete conformance evaluation.

## Automated checks

```bash
npm run test:e2e:a11y
```

The suite checks:

- Dashboard default state
- Expanded filter and open download dialog
- About page
- Programmatic names, roles, values, document structure, and color contrast

## Manual WCAG 2.1 AA checklist

Run this checklist before making or renewing a conformance claim:

- Complete every workflow using only the keyboard. Verify logical order,
  visible focus, skip links, Escape behavior, and both handles of range sliders.
- At 200% browser zoom and at 320 CSS pixels wide, verify that content reflows
  without two-dimensional scrolling or loss of controls.
- With reduced motion enabled, verify that chart and map motion is suppressed.
- With Windows High Contrast or macOS Increase Contrast enabled, verify that
  controls, selected states, charts, and focus indicators remain distinguishable.
- With VoiceOver and Safari, verify headings, landmarks, filters, dialogs,
  status announcements, map summary, and chart tables.
- With NVDA and Firefox or Chrome, repeat the primary filtering and download
  workflows and verify control names, states, and live announcements.
- Verify text and meaningful non-text contrast in every interactive state,
  including disabled, hover, focus, selected, error, and loading states.
- Verify that map information is available through the text summary and chart
  tables without requiring perception or operation of the map canvas.
- Record the pages, states, browsers, assistive technologies, dates, failures,
  and remediations included in the evaluation.

Use the W3C Website Accessibility Conformance Evaluation Methodology when a
formal conformance report is required.
