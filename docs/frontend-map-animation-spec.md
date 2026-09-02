# Crack Frontend Map and Animation Specification

Status: **Approved on 2026-09-01**
Scope: architecture-map presentation only
Implementation gate: **The locked Sprint 23–26 sequence is approved; each sprint keeps its own acceptance and Git gate.**

## 1. Purpose

Replace the current block-and-line architecture map with a compact, original, top-down pixel-art operations floor. Four labeled agent characters must visibly leave a staging area, travel along narrow orthogonal dotted paths, interact with themed application rooms, and return after their work is presented.

The result should feel lively and game-like while remaining an honest presentation of Crack's validated event stream. Animation must never claim that an agent is physically inside a system, that an exploit succeeded, or that model output owns the verdict.

## 2. Approved user direction

- Use the supplied Soul Knight screenshot only as high-level visual inspiration: compact top-down composition, industrial room dressing, small readable characters, perimeter equipment, and open walking space.
- Do not copy Soul Knight characters, sprites, rooms, props, sounds, palettes, or other assets.
- Use narrow dotted paths.
- Use no diagonal travel paths.
- Do not allow paths to cross over each other. Shared segments are allowed only when rendered as an intentional corridor or junction.
- Replace generic component boxes with themed rooms or stations.
- Use four separate, labeled characters:
  - Mapper
  - Authorization Tester
  - Verifier A
  - Verifier B
- Agents start in a staging area, walk to related components, perform two or three finite action cycles, and return.
- Use original 24–32 px-wide pixel sprites, scaled without interpolation blur.
- Complete the 32-event recorded replay in 45–50 seconds.
- Keep the map watch-only. Rooms and agents are not clickable.
- Add appropriate tool sounds.

## 3. Current defects being replaced

Measured in the current desktop rendering:

- Map bounds: approximately 826 × 826 CSS px.
- Agent glyph bounds: approximately 352 × 423 CSS px.
- Tool-effect bounds: approximately 493 × 493 CSS px.
- Effect bounds extend outside the map.
- Tool animation lasts 0.72–0.82 seconds while recorded events currently advance every 0.5 seconds.
- Nested SVG sizing mixes CSS pixels with map user units, causing extreme scale expansion.
- Agent and tool graphics have no bounded local sprite viewport.
- Effects anchor directly to a component center without a travel lane, safe interaction point, or clipping contract.
- Components are generic rectangles connected by crossing diagonal lines.

The replacement must not preserve this rendering structure.

## 4. Product goals

1. Make the map immediately understandable without requiring technical interaction.
2. Show one sequential active role at a time.
3. Give each agent a distinct silhouette, label, color, and tool.
4. Make movement slow enough to follow but short enough for a sub-minute replay.
5. Keep every sprite, effect, label, and path inside the map at every supported viewport.
6. Make each application component visually recognizable as a place, not a box.
7. Preserve exact event ordering, safe labels, and code-owned verdict semantics.
8. Keep all assets local, original, and deterministic.

## 5. Non-goals

- No playable game mechanics.
- No room, path, or agent interaction.
- No combat simulation, health, damage, score, inventory, or random behavior.
- No autonomous roaming or background attack loops.
- No parallel verifier choreography.
- No event-schema, coordinator, agent, runtime, target, scope-controller, provider, Docker, or ledger changes.
- No display of prompts, raw responses, credentials, source, request bodies, private records, or unvalidated event metadata.
- No claim that animation proves an attack or verdict.
- No copied commercial game assets or sound effects.

## 6. Visual direction

### 6.1 Overall composition

Use a top-down industrial security-lab floor with:

- dark blue-grey flooring;
- restrained red/orange Crack accents;
- cyan work lights;
- perimeter machinery and consoles;
- small environmental props that do not obstruct paths;
- subtle floor tiles or wear marks;
- clear negative space around agents;
- a compact game-room composition rather than a diagram canvas.

The reference image informs density and viewpoint only. Crack must use a distinct palette, room silhouettes, props, character designs, and tool effects.

### 6.2 Map coordinate system

- Fixed logical canvas: `960 × 540` units, 16:9.
- Desktop rendered width: fluid up to the existing content width.
- Map uses one view box and one coordinate system.
- All room, path, agent, label, and effect coordinates use map units.
- Nested SVG elements must declare explicit `x`, `y`, `width`, `height`, and `viewBox` values.
- `overflow: hidden` is mandatory at map and effect-layer boundaries.
- No CSS `width` or `height` may define a nested sprite inside SVG without matching map-unit geometry.

### 6.3 Proposed floor plan

```text
┌──────────────────────────────────────────────────────────────────┐
│  BROWSER PORTAL             ROLE & AUTH             SUBMISSIONS  │
│  reception terminal         security checkpoint     records bay │
│       ···············································         │
│       ·                                                    ·     │
│       ·              central operations corridor           ·     │
│       ·                                                    ·     │
│  FASTAPI WORKSHOP ························· GRADE LAB     ·     │
│       ·                                                    ·     │
│       ··································· SQLITE VAULT ···     │
│                                                                  │
│   [Mapper] [Authorization] [Verifier A] [Verifier B]              │
│                     STAGING DOCK                                 │
└──────────────────────────────────────────────────────────────────┘
```

Final paths must be authored as explicit orthogonal waypoint lists. No path is generated dynamically from arbitrary event data.

### 6.4 Path rules

- Paths are one or two map units wide.
- Visual treatment: small square or circular dots at regular intervals.
- Segments use only horizontal or vertical movement.
- Corners use a clean 90-degree turn with a slightly rounded floor marking if needed.
- Paths never visually cross. If two roles share a route, they use the same corridor segment.
- Each room has one fixed interaction point outside its visual footprint.
- Each staging slot has one fixed start and return point.
- Minimum safe inset from map edge: 32 units.
- Minimum sprite clearance from room art and map edge: 16 units.
- Props cannot overlap route clearance zones.

## 7. Themed application rooms

Each room keeps its canonical safe label permanently visible. Labels are presentation text, not user-controlled target content.

### Browser Portal — reception terminal

- Wide display wall, two small client terminals, browser-window motif.
- Cool blue light.
- Interaction point faces the central corridor.

### FastAPI API — workshop

- Compact service bench, request tubes or data canisters, status lamps.
- Teal light with orange activity pulse.
- Mapper's primary scan target.

### Role and Authentication — security checkpoint

- Gate, badge reader, lock light, narrow checkpoint lane.
- Amber and red accents.
- Authorization Tester's first interaction point.

### Submissions — records bay

- Filing terminal, sealed record crates, two student-record indicators.
- Blue-grey with one cool highlight.
- Used by Authorization Tester and both verifiers.

### Grade Lifecycle — grading laboratory

- Review console, draft/review/published indicator stack, document tray.
- Yellow, orange, and green state lamps.
- Must not visually imply that review-before-publish is enforced.

### SQLite Persistence — data vault

- Reinforced storage cabinet, cylindrical disk motif, reset/status lamp.
- Dark steel with cyan status light.
- Reset events highlight the room; no agent attack is shown for reset-only events.

## 8. Agent character system

### 8.1 Shared sprite contract

- Original pixel art only.
- Visible character width: 24–32 CSS px at desktop map size.
- Maximum visible character height: 40 CSS px including label clearance.
- Native sprite frame: `24 × 32` px or `32 × 32` px.
- Use integer scaling only.
- CSS must use `image-rendering: pixelated`.
- Each sprite sheet uses the same frame grid and animation names.
- Maximum combined character-and-effect bounds: `64 × 56` CSS px at desktop size.
- Character and effect bounds must remain inside the map.
- Labels sit above the sprite, use fixed safe names, and never scale larger than room labels.

### 8.2 Mapper

- Color: cyan/blue.
- Silhouette: small hood or visor, backpack scanner.
- Tool: handheld scanning lens or sweep emitter.
- Action: two slow scan sweeps across the FastAPI workshop.
- Label: `MAPPER`.

### 8.3 Authorization Tester

- Color: amber with muted violet detail.
- Silhouette: compact infiltrator/scout.
- Tool: probe wand, badge emulator, or key-shaped tester.
- Action: two probe cycles at Role and Authentication, then one inspection cycle at Submissions or Grade Lifecycle when related.
- Label: `AUTH TESTER`.

### 8.4 Verifier A

- Color: orange/red.
- Silhouette: sturdy engineer/miner.
- Tool: small pickaxe.
- Action: three measured pickaxe strikes at the safe interaction point.
- Label: `VERIFIER A`.

### 8.5 Verifier B

- Color: violet/cyan.
- Silhouette: technical specialist with compact emitter.
- Tool: short-range laser device.
- Action: two or three short laser bursts toward the safe interaction point.
- Label: `VERIFIER B`.

## 9. Animation grammar

Every active-role sequence uses the same finite state machine:

```text
docked -> enter -> walk -> face target -> interact -> acknowledge -> return -> docked
```

### Docked

- Sprite waits inside its labeled staging slot.
- No continuous attack, movement, or random idle loop.
- A subtle finite readiness blink may occur when the role is activated.

### Enter and walk

- Agent follows a predefined orthogonal waypoint list.
- Cardinal walk frames only: up, down, left, right.
- No diagonal sprite state.
- Target speed: 44–56 map units per second.
- Direction changes occur only at authored corridor corners.
- Agent label follows the sprite without covering room labels.

### Interact

- Agent stops at the room's fixed interaction point.
- Agent faces the room before using a tool.
- Tool motion runs two or three finite cycles.
- No effect crosses the room boundary or map edge.
- Tool effect remains visually secondary to the room and sprite.

### Acknowledge

- Related room receives a short outline or light pulse.
- Presentation copy identifies the accepted event.
- No damage, destruction, explosion, or success badge appears before code-owned consensus.

### Return

- Agent retraces or follows an authored return route.
- Agent returns to its own labeled staging slot.
- Next sequential role does not leave staging until previous role is docked.

## 10. Replay timing

Target recorded replay duration: **48 seconds**, acceptable range **45–50 seconds**.

| Phase | Time | Visible choreography |
| --- | ---: | --- |
| Session and preflight | 0–3 s | lab powers on; safe stage labels update |
| Mapper | 3–9 s | walk to FastAPI, two scan sweeps, return |
| Authorization Tester | 9–18 s | walk through authentication checkpoint, probe related rooms, return |
| Verifier A | 18–29 s | walk, two bounded-call interactions with three pickaxe strikes per key interaction, return |
| Verifier B | 29–40 s | walk, two bounded-call interactions with short laser bursts, return |
| Consensus and report | 40–48 s | rooms settle, code-owned gate resolves, report terminal state appears |

The 32 recorded events remain ordered. Event display and map choreography may group adjacent events into one phase, but no event may be skipped, reordered, synthesized, or shown before it is accepted.

Implementation note (2026-09-02): the complete authored 960 × 540 route set cannot fit the locked 48-second recorded replay while moving at the live 44–56-unit target speed. The implemented live director therefore remains at 50 map units per second, while recorded preview mode uses one fixed 210-unit presentation speed and may join only adjacent same-role cues through the fixed room-to-room corridors. This resolves the timing conflict without changing geometry, event order, acceptance timing, safe cue ownership, or the terminal timestamp.

## 11. Event-to-animation ownership

Add a pure presentation mapping from allowlisted event type to a finite cue:

```text
PresentationEvent -> safe relation -> MapCue[] -> AnimationDirector
```

`MapCue` may contain only:

- fixed agent ID;
- fixed room ID;
- fixed route ID;
- fixed action ID;
- finite cycle count;
- fixed safe caption;
- deterministic duration class.

It must not contain arbitrary coordinates, CSS, URLs, source paths, prompts, raw bodies, tokens, private prose, or target-controlled labels.

### Cue policy

- Preflight and session events: environment lighting and captions only.
- Mapper active event: Mapper leaves staging and scans FastAPI.
- Authorization discovery/retrieval events: Authorization Tester visits only mapped safe rooms.
- Reset events: SQLite room status pulse only; no gremlin attack.
- Verifier A safe active call: Verifier A pickaxe interaction.
- Verifier B safe active call: Verifier B laser interaction.
- Plan, check, completion, report, finding, and consensus events: static room or gate emphasis only unless explicitly defined in this document.
- Unsafe or unmatched events: no agent movement; safe text state remains visible.

## 12. Animation director

Implement one frontend-owned deterministic animation director.

Responsibilities:

- queue accepted presentation events in sequence order;
- translate them through the fixed cue table;
- run one agent choreography at a time;
- expose current cue to rendering and accessible status text;
- cancel cleanly on unmount or replay restart;
- reject stale cue completion from a prior replay generation;
- keep replay controls disabled while a replay is active;
- restore staging state after terminal completion;
- never delay or mutate backend event acceptance.

Recorded preview mode uses the fixed 48-second schedule. Live SSE mode consumes actual events and may queue finite cues, but it cannot invent timing, events, results, or activity.

## 13. Sound design

Use short event-tied sounds rather than one continuous `clink clink laser` loop. A continuous loop would become repetitive, obscure role changes, and imply activity during events that have none.

### Sound cues

- Walking: very quiet two-step pixel footfall pattern.
- Mapper: soft two-pass electronic scan.
- Authorization Tester: small probe click and restrained lock-reader chirp.
- Verifier A: two or three low-volume metal `clink` impacts synchronized with strikes.
- Verifier B: two or three short laser pulses synchronized with bursts.
- Consensus: one restrained mechanical confirmation tone.
- Failure: one low safe-stop tone; no alarm loop.

### Audio rules

- No audio before the user presses replay.
- Sound is enabled only inside the user-initiated replay session.
- Provide a visible `Sound on / Sound off` control; default level is low.
- Remember preference only in component state for the current page session unless separately approved.
- Stop all audio immediately when replay stops, restarts, fails, or unmounts.
- Do not layer more than one tool sound family at once.
- Use original generated/recorded assets with documented provenance and repository-compatible licensing.
- No external audio URL, CDN, runtime download, or copied game sound.

## 14. Rendering architecture

Recommended component split:

```text
ArchitectureExperience
  MapStage
    EnvironmentLayer
    PathLayer
    RoomLayer
    AgentLayer
    EffectLayer
    CaptionLayer
  ReplayStatus
  SoundControl
```

Recommended data modules:

- `map-layout.ts`: fixed room, staging, interaction, and waypoint geometry.
- `map-cues.ts`: exhaustive safe event-to-cue mapping.
- `animation-director.ts`: deterministic finite queue and cancellation behavior.
- `sprite-manifest.ts`: fixed local sprite and frame definitions.
- `audio-manifest.ts`: fixed local audio cue definitions.

No target-controlled input may reach these manifests.

## 15. Responsive behavior

### Desktop

- Full 16:9 floor visible without scrolling inside the map.
- Context panel moves below or beside the map only if it does not reduce the floor below its minimum readable size.
- Agent width remains 24–32 CSS px.

### Tablet

- Preserve full floor and all labels.
- Scale using one uniform map transform.
- Use integer sprite scaling when possible.

### Mobile

- Preserve the entire watchable floor in a dedicated map viewport.
- Do not reflow rooms into a different topology.
- Room labels may use shorter safe forms while accessible text retains full names.
- No horizontal page overflow.
- If integer sprite scaling and full-map fit conflict, prioritize bounded readable sprites and allow a fixed map viewport with controlled internal pan only if a later prototype proves it necessary. Default design remains scale-to-fit.

## 16. Accessibility

- Map has a concise accessible title and description.
- Current role, room, action, and state are announced through one polite live region.
- Character color is never the only role identifier; labels and silhouettes remain distinct.
- Sound never carries unique information.
- `prefers-reduced-motion` removes walking and tool transforms while preserving ordered room highlights, labels, captions, and timing controls.
- Sound control is keyboard accessible and has visible state.
- All text meets existing contrast standards.
- Watch-only map adds no fake buttons, draggable objects, or unreachable interaction targets.

## 17. Truth and security boundaries

- Animation is a presentation of accepted events, not evidence authority.
- SQLite ledger and code-owned consensus remain authoritative.
- Map highlights relationships, not physical execution location.
- Character attacks are visual metaphors, not claims of damage or compromise.
- Only verified consensus may display a verified terminal result.
- Preview remains committed synthetic fixture data.
- No provider call or ledger write occurs during provider-free replay.
- No secrets, credentials, prompts, raw model output, database rows, source, or user-provided labels render on the map.
- No configurable target, path, room, sprite, sound, route, origin, or command is accepted from the browser.

## 18. Asset plan and provenance

- Create original pixel-art room tiles, props, four agents, tools, and effects.
- Create original short audio cues.
- Store assets under fixed local frontend asset directories.
- Maintain `ASSET_PROVENANCE.md` listing creator/tool, date, purpose, license, and confirmation that no commercial game asset was copied.
- Do not commit the supplied reference screenshot.
- Do not trace or reproduce identifiable Soul Knight characters or room layouts.
- No external fonts, image services, analytics, or CDNs at runtime.

## 19. Required tests

### Geometry

- Every route segment is horizontal or vertical.
- No two unrelated path segments geometrically cross.
- Every room interaction point lies outside room art and inside map bounds.
- Every staging point lies inside staging dock bounds.
- Agent and effect bounding boxes remain inside the map for every cue.
- Character width never exceeds 32 CSS px at the desktop reference viewport.
- Combined effect bounds never exceed the specified maximum.

### Event mapping

- Every accepted presentation event maps exhaustively to a safe cue or explicit no-motion cue.
- Verifier tool effects appear only for safe active call events.
- Reset, plan, consensus, finding, report, failed, blocked, and unmatched events cannot create attack motion unless explicitly allowed above.
- Verifier B cannot leave staging until Verifier A returns.
- Duplicate/replayed sequence IDs cannot duplicate cues.

### Timing

- Successful recorded replay completes between 45 and 50 seconds with fake timers.
- Replay restart cancels previous timers, movement, and audio.
- Unmount cancels all pending work.
- Terminal state restores the replay control.

### Audio

- No sound before user gesture.
- Muted mode creates no audible playback.
- Tool sounds match the active role and stop on cancellation.
- No overlapping Verifier A and Verifier B audio.

### Accessibility and responsive QA

- Reduced-motion mode preserves information without transforms.
- Desktop, tablet, and mobile screenshots show no clipped agent, effect, room, label, or path.
- No page-level horizontal overflow.
- Keyboard reaches replay and sound controls in logical order.
- Browser console contains no warnings or errors.

## 20. Visual acceptance checklist

At minimum, capture and review:

1. Empty staging state.
2. Mapper walking and scanning FastAPI.
3. Authorization Tester probing the checkpoint.
4. Verifier A performing bounded pickaxe strikes.
5. Verifier B performing bounded laser bursts.
6. Code-owned consensus terminal state.
7. Reduced-motion state.
8. Sound-off state.
9. Desktop viewport.
10. Mobile viewport.

Acceptance fails if any agent or effect leaves the map, any path crosses diagonally, any room returns to a generic unlabeled box, or any animation implies a verdict before consensus.

## 21. Implementation sprints after approval

### Sprint 23 — Static floor and art system

Complexity: **4/5**
Recommended model: **GPT-5.6 Terra, high reasoning**

- Replace block diagram with original top-down room composition.
- Implement fixed logical geometry, orthogonal dotted routes, staging dock, themed rooms, labels, clipping, and responsive shell.
- Add original static room and character concept assets plus provenance.
- No movement, sound, backend, or event change.

Stop condition: approved static desktop/mobile map with all geometry tests passing.

### Sprint 24 — Character sprites and movement director

Complexity: **5/5**
Recommended model: **GPT-5.6 Terra, high reasoning**

- Implement four labeled sprite sets.
- Implement authored waypoint routes and finite dock/walk/interact/return states.
- Enforce sequential roles, clipping, cancellation, and reduced motion.
- No sounds or tool attack effects yet.

Stop condition: all four agents complete bounded journeys and return without clipping or overlap.

### Sprint 25 — Tool choreography and sound

Complexity: **4/5**
Recommended model: **GPT-5.6 Terra, high reasoning**

- Add scan, probe, pickaxe, and laser cycles.
- Add short event-tied local sound cues and sound control.
- Integrate 48-second recorded replay orchestration.
- Preserve safe exhaustive event mapping and code-owned verdict behavior.

Stop condition: complete 45–50 second replay passes timing, audio, cancellation, and event-order tests.

### Sprint 26 — Responsive polish and portfolio acceptance

Complexity: **3/5**
Recommended model: **GPT-5.6 Luna, high reasoning**

- Perform desktop, tablet, mobile, reduced-motion, forced-colors, sound-off, and browser-console QA.
- Fix only acceptance defects.
- Refresh portfolio screenshot after final approval.
- Update README and AGENTS.md with factual final state.

Stop condition: full offline acceptance, approved screenshots, unchanged ledger, and no provider-backed run.

No Sprint uses Sol unless a concrete blocker survives Terra/Luna implementation and independent review.

## 22. Git and approval workflow

For each implementation sprint:

1. Start from clean `main`.
2. Create one dedicated sprint branch/worktree.
3. Implement only that sprint's approved scope.
4. Run focused and full offline acceptance.
5. Review exact diff and security boundaries.
6. Commit one clear conventional change.
7. Fast-forward-only merge into `main` after acceptance.
8. Re-run post-merge gates.
9. Delete local sprint branch/worktree.
10. Push only the audited `main` to the existing intended origin.

No provider-backed Crack workflow, Docker runtime action, ledger write, secret read, or remote visibility change is part of these frontend sprints.

## 23. Approval decision

The user approved the locked document and the complete Sprint 23–26 implementation sequence on 2026-09-01. That approval does not authorize provider calls, Docker execution, ledger mutation, copied commercial assets, or expansion beyond the fixed synthetic school portal and architecture-map presentation scope.
