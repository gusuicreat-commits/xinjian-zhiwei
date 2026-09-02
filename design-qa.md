# Login layout restoration design QA

- Structural reference: `/var/folders/sq/lrmkk9hn4wvc78jdxswv9q4w0000gn/T/codex-clipboard-b4054d40-400c-48b4-a3ef-52710471aebb.png`
- Original product-style references:
  - `/Users/mac/Desktop/大创.2026/design-qa-assets/original-student-login.png`
  - `/Users/mac/Desktop/大创.2026/design-qa-assets/original-teacher-login.png`
- Final implementation screenshots:
  - `/Users/mac/Desktop/大创.2026/design-qa-assets/student-login-restored-style.png`
  - `/Users/mac/Desktop/大创.2026/design-qa-assets/teacher-login-restored-style.png`
  - `/Users/mac/Desktop/大创.2026/design-qa-assets/student-login-restored-mobile.png`
  - `/Users/mac/Desktop/大创.2026/design-qa-assets/teacher-login-restored-mobile.png`
- Desktop viewport: 1117 x 837 CSS px
- Mobile viewport: 390 x 844 CSS px
- Density: browser screenshots captured at the active app density; implementation evidence was compared at matching CSS viewport sizes without resampling.
- State: empty student and teacher login forms, default theme.

## Full-view comparison evidence

The original product screenshots and final implementation screenshots were opened together in one comparison view. The final version keeps only the requested structural change—a full-width header and centered single login panel—while restoring the original Swiss-editorial visual system: warm off-white surfaces, electric-blue structural accent, black display typography, square corners, flat borders, underline inputs, and shadow-free panels.

## Focused region comparison evidence

The header, card edge, fields, and primary CTA are readable in the full-view comparison, so separate crops were unnecessary. Computed desktop tokens confirm the restoration: page `rgb(244, 243, 238)`, header `rgba(244, 243, 238, 0.96)`, card `rgb(248, 247, 242)`, `0px` card radius, and no card shadow.

## Required fidelity surfaces

- Fonts and typography: the original heavy black display heading, compact monospaced blue kicker, muted supporting text, and restrained header type hierarchy are restored.
- Spacing and layout rhythm: the requested centered card and full-width header remain; the panel uses the original square editorial grid, flat border, generous whitespace, and blue vertical axis.
- Colors and visual tokens: restored to `--studio-bg`, `--studio-panel`, `--studio-ink`, `--studio-muted`, `--studio-line`, and `--studio-blue`. The cool white/rounded-card treatment from the previous iteration has been removed.
- Image quality and asset fidelity: the original Element Plus monitor icon is restored in the brand lockup. No substitute raster logo, generated imagery, or decorative CSS illustration remains.
- Copy and content: existing field labels, role context, security notes, CTAs, and role-switch destinations are preserved.

## Interaction and runtime checks

- Student login navigates to `#/student`.
- Teacher login navigates to `#/teacher`.
- Header role-switch links remain available on both routes.
- Browser console errors from both login pages: none.
- Desktop and 390 px mobile layouts have no horizontal overflow; mobile cards measure 362 px with 14 px side margins.
- ESLint passed, 26 unit tests passed, and the review build passed.

## Findings

No actionable P0, P1, or P2 findings remain.

## Comparison history

- Earlier iteration: P1 visual-system drift. The layout request unintentionally replaced the warm neutral/blue flat editorial system with a cool white rounded-card style, raster brand mark, and elevated shadow treatment.
- Fix: restored the original product tokens, monitor icon, square geometry, underline inputs, flat panel treatment, and warm background while retaining the approved full-width-header/centered-form structure.
- Post-fix evidence: the final desktop and mobile screenshots above show the restored style with no overflow or interaction regressions.

## Follow-up polish

- P3: student and teacher cards have different heights because only the student route contains two security notices. This is content-driven and does not affect alignment or shared visual language.

final result: passed
