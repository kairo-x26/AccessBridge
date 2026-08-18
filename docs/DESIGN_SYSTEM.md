# Design system

The interface is built for coordinators who work in it all day: dense, calm and legible,
with one memorable idea that carries meaning rather than decoration.

## Principles

1. **The route is the product.** A referral's journey is drawn as a transit line. It
   appears small in every queue row and in full on the referral page, with the evidence
   for each stop.
2. **Proposed is not done.** Anything the agent proposed or read automatically is
   **dashed violet**. Anything a person verified, or that evidence proves, is **solid**. The
   rule holds everywhere: route stops, extracted fields, approval cards, the agent panel
   and notices.
3. **Color always has words.** Every status color comes with a label; screen readers get
   the route as a sentence.
4. **Plain language.** Sentence case, plain verbs, the user's vocabulary. Errors say what
   happened and what to do next.

## Tokens (`frontend/src/styles/tokens.css`)

| Token | Light | Dark | Means |
|---|---|---|---|
| `--paper` / `--surface` | `#f5f7f6` / `#ffffff` | `#0f171c` / `#162129` | Page and panel backgrounds |
| `--ink` / `--ink-2` / `--ink-3` | `#18262f` … `#5a6a73` | `#e4ecee` … `#93a3aa` | Text, strongest to quietest |
| `--route` | `#0e6b66` | `#4fc1b8` | Progress, primary actions |
| `--agent` | `#5847b0` | `#a99bff` | Proposed by the agent, not yet verified |
| `--exception` | `#8f5600` | `#e8a84a` | Operational exception, needs a person |
| `--verified` | `#2c7a3a` | `#6fcb7e` | Confirmed, completed, evidence-backed |
| `--alert` | `#b3261e` | `#ff8a80` | Failures and urgent escalations only |
| `--seq-1…5` | teal ramp | teal ramp | Ordered data (validated: monotone, distinct steps, clears the surface) |

Radius encodes nesting (6 px for controls, 10 px for panels), not decoration. Spacing is a
4 px scale. Dark mode is a separate, deliberately chosen token set, not an inversion.

## Typography

**Atkinson Hyperlegible Next**, designed for low-vision legibility, which suits the
WCAG 2.2 AA target. One family; weight carries hierarchy. A 1.125 modular scale around a
15 px working size (13, 14, 15, 17, 21, 27 px). Tabular numerals in tables, proportional
numerals for large figures.

## Components

| Component | Notes |
|---|---|
| `RouteLine` (mini) | SVG; passed stops solid, current stop ringed, exception as an amber diamond with a branch, closed as an end bar; spoken label "Sent to specialist (stop 4 of 7)" |
| `RouteMap` | Vertical route with evidence chip, actor and time per stop; exceptions branch in amber; pending proposals render as dashed violet stops with inline approve/reject |
| `Button` | primary, secondary, quiet, danger; `busy` sets `aria-busy` and disables |
| `Field` | Wires label, hint and error to the control (`aria-describedby`, `aria-invalid`) |
| `Notice` | info, warning, error, success, agent (dashed) |
| `Panel` | Section with heading; `tone="agent"` for agent-owned content |
| `StatusBadge`, `Tag`, `EvidenceChip` | Labeled color; evidence is solid when verified, dashed when proposed |
| `Dialog` | Native `<dialog>`: focus trap and Escape for free |
| Charts | Hero figure, stat tiles, meters, column and bar charts with focusable marks and a table view; built to the dataviz method (thin marks, one baseline, validated ramp) |

## Layout

A narrow navigation rail (icons with labels, approval counts) and a work area. The referral
page uses three columns (route, package and messages, agent activity), collapsing to two at
1280 px and one at 900 px. Below 760 px the rail becomes a bottom bar; below 640 px queue
rows fold secondary columns under the patient's name.

## Accessibility checks

* axe-core runs in component tests and on 11 light-mode and 5 dark-mode screens in
  end-to-end tests (WCAG 2.2 A/AA, including contrast): zero violations.
* Visible focus everywhere; skip link; reduced motion respected; motion is limited to
  dialog and toast entrances.
