# Pulse Practice Generator — UI Redesign Prompt

Continue working in the existing **Pulse Practice Generator** project.

> **Reference image:** Use the provided dark cyber / neon-green generator mockup as the primary visual reference.

---

## Critical rule

This task is a **UI/UX redesign only**.

Do **not** rewrite or change the product logic.

The generator already works. Preserve all existing behavior, data flow, API contracts, state transitions, and local pipeline integration.

### Do not break

- Workspace creation
- Audio upload
- Background upload
- Metadata extraction and editing
- Difficulty selection
- Advanced settings
- Generation job creation
- Real progress polling
- Pipeline stage updates
- Job logs
- Cancellation
- Retry/resume behavior
- Result rendering
- Artifact downloads
- `.osu` and `.osz` generation
- Game preview
- Editor preview
- API health state
- Workspace state
- Existing local FastAPI integration
- Existing tests

Do not replace real progress with fake animation.

Do not remove any useful information merely to simplify the layout.

If markup must be refactored, preserve observable behavior and existing event bindings.

---

# Goal

Redesign `generator.html` and the generator frontend so the page feels like a polished, professional local beatmap-generation tool.

The new visual direction should be:

- Near-black background
- Dark green / blue-black layered panels
- Neon green primary accent
- Muted cyan secondary accent
- Subtle glow
- Terminal-inspired typography
- Clean dashboard hierarchy
- Compact professional spacing
- Stronger visual feedback
- Desktop-first
- Responsive where practical
- Original visual identity
- Not childish
- Not overloaded
- Not a direct copy of another product

The result should match the provided reference mockup closely in mood, hierarchy, density, and component treatment.

---

# Page structure

Rebuild the generator page around this layout:

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Header: Brand | Wizard steps | API state | Workspace | Settings        │
├───────────────────┬─────────────────────────────────────────────────────┤
│ Workspace sidebar │ Main step content                                  │
│                   │                                                     │
│ Audio             │ Upload / Metadata / Difficulty / Generate / Result │
│ Background        │                                                     │
│ Difficulties      │                                                     │
│ Job state         │                                                     │
│ Privacy           │                                                     │
├───────────────────┴─────────────────────────────────────────────────────┤
│ Optional compact footer / utility links                                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

# 1. Header

Replace the oversized introductory hero with a compact professional application header.

Include:

- Pulse Practice logo / original generator mark
- `PULSE PRACTICE`
- Small subtitle: `OSU MAP GENERATOR`
- Wizard navigation:
  - Upload
  - Metadata
  - Difficulties
  - Generate
  - Results
- Local API status
- Workspace short ID
- Settings/help buttons where useful

### Header styling

- One horizontal dark panel
- Thin neon-green border
- Subtle gradient
- Compact height
- Active wizard step with green outline/glow
- Completed steps with check state
- Upcoming steps muted
- Avoid excessive height

Do not break current wizard navigation rules.

---

# 2. Wizard stepper

The wizard must look like a connected process rather than unrelated buttons.

Each step should include:

- Number
- Label
- State:
  - upcoming
  - active
  - completed
  - error when applicable

Use:

- Connected angled segments or subtle connector lines
- Bright green active state
- Checkmark for completed state
- Muted gray upcoming state
- Clear keyboard focus state

Do not allow invalid step navigation that current logic already prevents.

---

# 3. Left workspace sidebar

Make the sidebar compact and highly informative.

## Workspace card

Show:

- `WORKSPACE`
- `LOCAL SESSION`
- Short privacy note

## Status tiles

Use compact stacked tiles for:

### Audio

- Icon
- Filename
- Duration
- Format
- File size
- Upload state

### Background

- Optional / uploaded state
- Filename when available

### Difficulties

- Selected difficulty names
- Empty state when none selected

### Job status

- Idle
- Queued
- Running
- Completed
- Failed
- Cancelled

Use meaningful icons and badges.

## Privacy card

Keep current privacy messaging, but present it as a lower-priority compact card:

- Uploaded files remain local
- No cloud processing
- No external AI service
- Local workspace isolation

Do not remove any privacy text that is important to the product.

---

# 4. Shared main-panel design

All wizard steps should use one consistent main content surface.

Requirements:

- Large dark panel
- Thin green-tinted border
- Subtle internal gradient
- Rounded corners
- Compact top label such as `STEP 1`
- Strong title
- Short description
- Clear internal sections
- Less dead space
- Consistent footer actions

The content should feel like a serious desktop tool.

---

# 5. Upload step

Redesign the upload interface into a large, central dropzone.

## Empty state

Show:

- Large original audio-file icon
- `DRAG & DROP YOUR SONG HERE`
- `or click to browse`
- Supported formats:
  - MP3
  - WAV
  - OGG
  - FLAC
- Maximum size
- Primary `CHOOSE FILE` button
- Local-only privacy hint

## Dropzone styling

- Dashed neon-green border
- Dark dotted/grid texture
- Subtle hover glow
- Strong drag-over state
- Large click target
- Keyboard accessible

## Uploaded state

After upload, replace the empty state with a polished file summary:

- Filename
- Duration
- Type
- Size
- Detected title
- Detected artist
- Upload success state
- Replace file
- Remove file

Do not alter upload logic or metadata-suggestion behavior.

---

# 6. Metadata step

Redesign the metadata form.

Fields should remain functionally identical.

Use grouped sections:

## Core metadata

- Title
- Artist
- Creator

## Optional metadata

- Unicode title
- Unicode artist
- Source
- Tags

## Artwork

- Optional background upload
- Preview when available

## Detected metadata

Show detected values as suggestions, clearly separate from confirmed user values.

Do not overwrite user-entered values automatically.

Use:

- Strong labels
- Consistent input height
- Inline validation
- Clear required-field states
- Better focus states
- Helpful small descriptions

---

# 7. Difficulties step

Show difficulty options as polished selectable cards.

Cards:

- Easy
- Normal
- Hard

Each card should show:

- Name
- Short behavior description
- Candidate count
- Estimated relative processing cost
- Selected state
- Optional advanced settings button

Use no official star-rating claims.

## Advanced settings

Keep existing settings functional.

Group them cleanly:

- Candidate count
- Root seed
- Timing variation
- Tournament enabled
- Hybrid assembly enabled

Do not change default values or generation behavior.

---

# 8. Generate step

This is the most important visual screen.

Match the reference mockup closely.

## Top status strip

Show the real current status message with:

- State label
- Message
- Dismiss action where supported

Variants:

- Info
- Success
- Warning
- Error

## Summary metrics

Show four compact cards:

- Overall progress
- Current stage
- Elapsed time
- Stages completed

Progress must use actual backend state only.

## Pipeline timeline

Show all real stages in a compact vertical timeline/table.

Each stage must visibly support:

- queued
- running
- completed
- failed
- cancelled

For each stage show where available:

- Status icon
- Stage name
- Short message
- Duration
- Current candidate progress
- Difficulty

Suggested styling:

- Green `OK` badge for completed
- Bright `RUN` state for active
- Muted upcoming rows
- Red failure state
- Thin progress connector across stage numbers

Do not hide stage names.

Do not fake elapsed times.

## Job logs

Replace oversized individual log cards with a denser terminal-style log panel.

Each row can contain:

- Time
- Level
- Message

Requirements:

- Scrollable
- Monospace
- Clear levels
- Copy logs action if practical
- Expand/collapse
- Preserve all existing log information

Do not render every log as a huge card.

## Actions

Use a consistent bottom action bar:

- Back
- Cancel Job
- Retry / Start Generation when appropriate

Disable actions based on current real state.

Do not allow duplicate generation jobs.

---

# 9. Results step

Make completion feel rewarding and clear.

Show:

## Mapset summary

- Song title
- Artist
- Duration
- Selected difficulties
- Generation mode
- Final status

## Difficulty result cards

For each selected difficulty show:

- Version name
- Object count
- Champion candidate
- Quality score
- Hybrid score
- Promotion result
- Open in Game
- Open in Editor
- Download `.osu`

## Final package

Prominent `.osz` card:

- Human-readable filename
- Package size
- Included difficulties
- Audio included
- Background included when available
- Download `.osz`

Keep all existing artifact actions intact.

---

# 10. Buttons

Create a consistent button system.

## Primary

- Neon green border/fill
- Used for:
  - Choose File
  - Continue
  - Start Generation
  - Download `.osz`

## Secondary

- Dark surface
- Green/gray outline
- Used for:
  - Back
  - Open Editor
  - Open Game
  - Replace file

## Destructive

- Muted red
- Used for:
  - Cancel Job
  - Remove file
  - Delete workspace

## Disabled

- Clearly disabled
- No misleading hover state

Add focus-visible styles.

---

# 11. Visual design tokens

Centralize styling with CSS custom properties.

Example categories:

```css
--bg-page
--bg-panel
--bg-panel-elevated
--bg-input
--border-default
--border-accent
--text-primary
--text-secondary
--text-muted
--accent-green
--accent-green-soft
--accent-cyan
--success
--warning
--danger
--radius-sm
--radius-md
--radius-lg
--shadow-panel
--glow-accent
```

Do not scatter unexplained color values across many files.

---

# 12. Typography

Use a technical, readable hierarchy.

Recommended behavior:

- Strong display heading for major step titles
- Monospace or code-inspired type for labels and status
- Highly readable body font
- Uppercase micro-labels with letter spacing
- Avoid oversized text
- Avoid cramped paragraphs

Do not introduce font files unless already present or explicitly approved.

---

# 13. Responsive behavior

Desktop-first, but remain usable on smaller screens.

Suggested breakpoints:

- Large desktop: sidebar + main content
- Laptop: narrower sidebar
- Tablet: sidebar collapses above main content
- Small screens: stacked wizard and cards

Do not target a full mobile generator experience in this task.

Prevent horizontal overflow.

---

# 14. Accessibility

Preserve or improve:

- Keyboard navigation
- Visible focus states
- Proper form labels
- Button labels
- Status text in addition to color
- Sufficient contrast
- Reduced-motion preference
- Accessible drag-and-drop fallback

Do not communicate status through color alone.

---

# 15. Files to focus on

Focus on generator frontend presentation, such as:

- `generator.html`
- `src/generator/GeneratorApp.ts`
- `src/generator/styles/generator.css`
- generator step components
- generator presentational components

Create small reusable UI components if needed.

Keep API and pipeline logic separate from visual components.

Do not modify backend generation algorithms.

---

# 16. Functional preservation checklist

After redesign, confirm all of these still work:

- API health status
- Workspace creation
- Audio upload
- Metadata suggestions
- Metadata editing
- Difficulty selection
- Advanced settings
- Generation start
- Real progress updates
- Current-stage updates
- Candidate progress
- Log updates
- Cancellation
- Retry
- Result loading
- `.osu` download
- `.osz` download
- Open in Game
- Open in Editor
- Workspace cleanup

---

# 17. Strict restrictions

Do not:

- Change API routes
- Change request/response schemas
- Change generation stages
- Change scoring
- Change map generation algorithms
- Change tournament behavior
- Change hybrid behavior
- Change export behavior
- Change naming rules
- Change workspace isolation
- Add fake progress
- Remove useful logs
- Remove validation messages
- Begin AI/ML work
- Add sliders or spinners
- Add a database
- Add cloud services

This task is strictly a frontend visual redesign.

---

# 18. Testing

Run targeted checks.

At minimum:

```text
focused generator frontend tests
typecheck
one production build
```

Add or update tests only where markup or presentation structure requires it.

Do not weaken behavioral tests to make the redesign pass.

Do not repeatedly run unnecessary heavy full-project checks.

---

# 19. Final report

After completion, report:

1. Files created
2. Files modified
3. Header changes
4. Stepper changes
5. Sidebar changes
6. Upload-step changes
7. Metadata-step changes
8. Difficulty-step changes
9. Generate-step changes
10. Log presentation changes
11. Results-step changes
12. Responsive behavior
13. Accessibility improvements
14. Functionality explicitly preserved
15. Tests run
16. Typecheck result
17. Build result
18. Manual interaction result
19. Anything not tested
20. Any remaining visual limitations

The final result must be a major visual upgrade without breaking the existing working generator.
