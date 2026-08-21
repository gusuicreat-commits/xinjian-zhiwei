# Design QA — Swiss Studio UI Iteration

## Comparison target

- Source visual truth: `/var/folders/sq/lrmkk9hn4wvc78jdxswv9q4w0000gn/T/codex-clipboard-cfabea09-d088-43e7-98c8-ae5451c155bf.png`
- Source pixels: `2560 × 7146`, PNG, 1× density.
- Implementation routes: `/login`, `/student`, `/teacher/login`, `/teacher`.
- Implementation viewport: `1117 × 767` CSS pixels, 1× density.
- Implementation screenshots:
  - `design-qa-assets/student-login-desktop-final.jpg`
  - `design-qa-assets/student-desktop.jpg`
  - `design-qa-assets/teacher-login-desktop-final.jpg`
  - `design-qa-assets/teacher-desktop.jpg`
- State: desktop, warm-light theme, authenticated dashboard empty/demo state, login forms idle.
- Normalization: the source is a long-form agency page while the implementation is a functional web application. Comparison therefore uses the source's visible design language and above-the-fold proportions rather than copying its marketing section order or copy. Pixel density is 1× for both; crops are compared at their native widths without resampling.

## Full-view comparison evidence

The source and all four implementation screenshots were opened together in the same comparison input. The implementation preserves the source's defining system: warm off-white field, saturated blue structural axis, black oversized display typography, mono micro-labels, asymmetric two-column composition, thin hairline rules, rectangular controls, and shadowless linear information surfaces.

The application intentionally keeps its existing operational information architecture. Student and teacher dashboards translate the source's vertical axis into a 12-column hero divider, navigation/status rails, numbered-feeling micro labels, and linear metric rows instead of introducing marketing sections that would displace real product functions.

## Focused-region comparison evidence

The authentication hero and form regions were compared separately because title wrapping, axis placement, input treatment, and CTA proportions were too small to judge confidently in the full dashboard view. The final focused captures show:

- a stable `7 / 5` editorial split;
- a single saturated blue rail occupying roughly 5% of the desktop width;
- display copy constrained to the safe left grid rather than colliding with the rail;
- underline-only inputs and rectangular blue CTAs;
- no decorative illustration, gradient, floating card, large radius, or shadow.

## Required fidelity surfaces

- Fonts and typography: Inter/Helvetica Neue with PingFang SC/Source Han Sans SC fallbacks; display text uses 750–800 weight, `0.94–0.98` line height, negative tracking, and controlled logical line breaks. Micro labels use a mono stack. Body copy stays at 11–14 px with clear contrast hierarchy.
- Spacing and layout rhythm: application content is capped to a 1280 px system with 12-column hero grids, 48 px desktop gutters, 72–128 px section rhythm, and consistent hairline dividers. Cards are flattened into rows and split panels with no elevation.
- Colors and visual tokens: `#F4F3EE`, `#111111`, `#555555`, `#888888`, and `#243BFF` are centralized in the final theme layer. Computed-style audits found no visible gradients, large radii, or box shadows across the four core routes.
- Image quality and asset fidelity: the source visual contains no required photographic or illustrative asset in the design language being transferred. The prior student hero illustration is hidden rather than replaced with a placeholder. All operational icons come from the existing Element Plus icon library.
- Copy and content: all product-specific Chinese copy, data labels, diagnostic language, task status, navigation, and security notices remain intact. Only display-title line grouping changed; wording did not.
- Responsiveness: desktop rendering has no horizontal overflow on all four routes. Tablet/mobile breakpoints collapse the 12-column regions, stack authentication panes, remove the desktop rail, preserve large-title hierarchy, and convert teacher navigation to the existing bottom navigation. The in-app browser did not expose viewport resizing, so an alternate mobile screenshot could not be captured without switching browser surfaces; this remains a non-blocking capture gap rather than an identified layout defect.
- Accessibility: visible focus rings use the brand blue, controls retain semantic button/input markup, reduced-motion rules remove entrance animation, and persistent navigation remains outside the refresh flash layer.

## Findings

- No actionable P0, P1, or P2 findings remain.
- [P3] Capture a physical mobile viewport in a future device/browser QA pass.
  - Location: all four responsive routes.
  - Evidence: responsive rules are implemented, but the selected in-app browser surface could not change viewport size.
  - Impact: no current desktop defect; this only limits screenshot evidence for the smallest breakpoint.
  - Follow-up: capture 390 × 844 and 768 × 1024 states when the selected browser exposes viewport controls.

## Comparison history

### Pass 1

- Finding: [P2] the authentication display titles extended into the blue structural rail with black glyphs, reducing contrast and making Chinese wrapping feel accidental.
- Evidence: `design-qa-assets/student-login-desktop.jpg` and `design-qa-assets/teacher-login-desktop.jpg`.
- Fix: constrained the hero-copy width to the safe left grid, reduced the desktop Chinese display scale slightly, and grouped both titles into deliberate logical lines without changing copy.

### Pass 2

- Post-fix evidence: `design-qa-assets/student-login-desktop-final.jpg` and `design-qa-assets/teacher-login-desktop-final.jpg`.
- Result: both titles remain large and editorial, line breaks are intentional, and the blue rail is unobstructed. No new P0/P1/P2 issue was observed.

## Primary interactions tested

- Student and teacher login fields accept text and enable their submit buttons.
- Student section navigation and teacher section navigation scroll to their target regions.
- Teacher search filters to the existing empty state and restores after clearing.
- Teacher navigation collapse/expand remains functional.
- Student and teacher manual refresh actions still show and dismiss the white refresh transition.
- All four routes render without visible application error overlays or horizontal overflow.

## Implementation checklist

- [x] Unified design tokens and font hierarchy.
- [x] 12-column desktop grid and asymmetric hero divider.
- [x] Linear, shadowless cards and status rows.
- [x] Rectangular CTA and underline-input system.
- [x] Student and teacher dashboards restyled without logic changes.
- [x] Student and teacher login flows restyled without auth changes.
- [x] Chart palettes aligned to the black/white/blue system.
- [x] Desktop visual comparison and focused auth comparison completed.
- [x] Type-check, lint, production build, formatting, and 26 unit tests passed.

## Follow-up polish

- Capture tablet and mobile screenshots when viewport emulation is available in the selected browser.

final result: passed
