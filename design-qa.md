# Phase 6 学生端视觉实现 QA

- Source visual truth: `docs/design-qa/phase6-student-ui/reference.png`
- Login implementation: `docs/design-qa/phase6-student-ui/login.png`
- Dashboard implementation: `docs/design-qa/phase6-student-ui/dashboard.png`
- Mobile implementation: `docs/design-qa/phase6-student-ui/dashboard-mobile.png`
- Full comparison: `docs/design-qa/phase6-student-ui/full-comparison.jpg`
- Focused dashboard comparison: `docs/design-qa/phase6-student-ui/dashboard-comparison.jpg`
- Desktop viewport: 1680 × 940
- Mobile viewport: 390 × 844
- State: device-authenticated test fixture, online heartbeat, two generic metric series, error logs, deterministic rule match, ranked causes and Level 1 guidance

## Findings

No remaining P0, P1 or P2 visual findings.

- The source is a composite design board showing login and dashboard side by side. The implementation intentionally uses separate `/login` and `/student` routes because they are distinct application states.
- The source contains a named student, class, DHT11 task, ESP32 model, Wi-Fi details and fixed progress values. The implementation intentionally replaces these with API-backed device data or explicit “待配置” states because those facts have not been supplied or confirmed.
- The source evidence and cause lists contain more items. The implementation renders only evidence, causes and hints returned by the current deterministic backend; it does not invent rows to fill the layout.

## Required fidelity surfaces

- Fonts and typography: Chinese system UI stack, dark-brown headings, compact 9–15 px monitoring text, weighted section titles and truncation match the source hierarchy. No clipped desktop headings or controls were observed.
- Spacing and layout rhythm: warm 76 px top bar, 168 px sidebar, two-card overview, three-column monitoring row, three-column reasoning row and bottom action bar reproduce the source composition. At 1680 × 940 all three primary actions are visible and there is no horizontal overflow.
- Colors and visual tokens: warm ivory canvas, copper brand accents, light card borders, blue chart/action tokens, green online/success, amber warning and red diagnosis states track the source palette.
- Image quality and asset fidelity: the brand mark and login chip illustration are real raster assets generated for the project and placed at their measured slots. Standard interface icons use `@element-plus/icons-vue`; no handcrafted SVG, emoji or CSS icon substitutes are used.
- Copy and content: product naming and student-terminal labels follow the source. Hardware-, account- and task-specific copy remains dynamic or explicitly unconfigured to preserve the project’s data-truth boundary.

## Focused comparison evidence

`dashboard-comparison.jpg` compares the source dashboard region and the implementation at the same desktop state. The focused pass checked top/task/device proportions, log density, chart legend and grid, red diagnosis card, evidence/cause/guidance cards and the three colored actions. No actionable alignment or density mismatch remains.

## Responsive and interaction checks

- 390 × 844 mobile capture has `scrollWidth=390`, no horizontal overflow and no Vite error overlay.
- Sidebar collapse and expand both work and expose stable accessible names.
- Refresh restores API-backed state.
- “请求教师协助” writes feedback to the isolated preview backend and displays the saved confirmation.
- Browser console error log is empty.

## Comparison history

### Iteration 1

- [P2] The three primary action buttons started below the 940 px desktop viewport.
  - Fix: reduced monitoring-row height, compacted lower-card headers and hint rows, and tightened grid rhythm.
  - Post-fix evidence: `dashboard.png`; button bounds are top 893 px / bottom 937 px and all three are fully visible.
- [P2] The collapsed sidebar toggle lost its accessible name when its text was visually hidden.
  - Fix: added a state-dependent `aria-label` for “收起菜单” and “展开菜单”.
  - Post-fix evidence: browser role queries resolve exactly one control in both states.

## Follow-up polish

- [P3] Replace the generated brand assets with official source files if the project later receives a formal logo package.
- [P3] Once real experiment metadata exists, the overview card can use the richer progress and deadline fields shown in the reference without changing the layout.

final result: passed
