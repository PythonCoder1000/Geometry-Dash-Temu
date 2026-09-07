# The Complete Geometry Dash Physics Bible (Update 2.2)
### Gamemodes • Buffering • Hitboxes • Special Blocks — Full Combined Reference

---

## PART 0 — HOW TO READ THIS DOCUMENT

Units glossary used throughout: **1 block** (one editor grid square) = **30 units**. **1 Vel** (velocity unit) = **60 units/second**. "G" = the gravity-direction variable: +1 when falling downward (normal gravity), −1 when falling upward (flipped gravity). So "11.18G" means 11.18 Vels in the current gravity-down direction.

Every specific number below is flagged as either:
- **Well-corroborated** — appears in the authoritative reverse-engineering source (GD Docs / boomlings.dev) and/or is independently confirmed by a second serious source (GD Creator School, official wiki).
- **Single-source estimate** — comes from one community source (e.g., a smaller GitHub repo) and should be treated as approximate.
- **Undocumented / qualitative only** — no numeric figure exists anywhere in accessible sources; only descriptive behavior is known.

There are **exactly eight official gamemodes** in Geometry Dash as of Update 2.2 (December 2023): Cube, Ship, Ball, UFO, Wave, Robot, Spider, and **Swing** (the only new movement gamemode 2.2 added). There is **no gamemode called "Swoop"** — that name does not exist in any official RobTop source.

---

## PART 1 — GAMEMODE PHYSICS

### 1.1 The two physics "families"
Most modes (Cube, Ship, Ball, UFO, Robot, Swing) are affected by a constant downward *acceleration* — an artificial "gravity" applied every game tick. Two modes — **Wave and Spider — have no gravity or acceleration whatsoever**; they move in perfectly straight lines / teleport instantly and respond immediately to input.

### 1.2 Three kinds of "jump"
1. **True jump** (burst of upward velocity): Cube, UFO, Robot.
2. **Continuous climb** (push against gravity while held): Ship, Wave.
3. **Gravity flip** (no jump at all): Ball, Spider, Swing.

### 1.3 Core numbers table (well-corroborated, GD Docs)

| Gamemode | Ticks held | Can click midair? | Max fall velocity | Jump/action velocity (1x speed) |
|---|---|---|---|---|
| Cube | 1 | No | −15G | 11.18G |
| Ship | 2 | Yes | 8G up (hold) / −6.4G (release) | not fully documented (see §2.4) |
| Ball | 1 | No | −15G | 3.354G (3/10 of cube), then flips gravity |
| UFO | 2 | Yes | −6.4G | 7G (constant at every speed) |
| Wave | 2 | Yes | N/A (no gravity) | 5.193G up / −5.193G down (1x) |
| Robot | 1 | No | −15G | 5.59G (≈1/2 of cube); gravity disabled while holding |
| Spider | 1 | No | −15G | instant teleport |
| Swing | 2 | Yes | −8G | multiplies current y-velocity by 0.8, then flips gravity |

GD Docs states the two shortcuts verbatim: "Robot is also just 1/2 of cube jump velocity and ball is 3/10 of cube jump velocity."

**Engine tick-ordering quirk (why the "second jump" of a hold feels higher):** on a fresh cube click, the game sets velocity *first* then applies one tick of gravity in the same tick — so at 1x/240 TPS the first-tick velocity is really 11.18 − 0.216 ≈ 10.964, not the full 11.18. But on the *second* jump of a hold or a buffered click, gravity is processed *before* the jump, so the full force applies on the first tick. This is documented directly on GD Docs and is the mechanical explanation for buffered/held jumps feeling slightly higher — see Part 2 for the full buffering treatment.

### 1.4 Per-gamemode detail

**Cube 🟩 (Update 1.0).** Baseline mode: click/tap for a fixed jump burst, subject to constant gravity → parabolic arc, no air control. Click velocities by speed portal: 10.62G (0.5×), 11.18G (1×), 11.42G (2×), 11.23G (3×), 11.23G (4×). Max fall −15G. **Single-source estimate** for downward acceleration ≈ −72 blocks/s² (lily-pi/GeometryPhysics; not a verified decompiled constant). Dies on hitting the side or bottom of a block.

**Ship 🚀 (Update 1.0).** Hold to fly up, release to fall — a momentum/inertia mode that carries drift through the hold/release transition. Max upward velocity 8G (hold), max downward −6.4G (release) — the only mode with two distinct maxima. **Single-source estimate**: acceleration ≈ −25 blocks/s² (lily-pi/GeometryPhysics), roughly a third of the cube's rate. **This is the one gamemode whose exact hold/release acceleration remains genuinely unresolved** — GD Docs marks its per-speed hold/release table rows "Skipped for now" and explicitly warns "ship is still not fully understood, so don't rely on it for ship." Gets floatier at higher speed. 2.2 made upside-down/dual ship gravity consistent with normal ship gravity (old-vs-new exact values undocumented; restorable via Legacy Options). Dies only on hitting the side of a block. "Feathering" (rapid taps) is the pro technique.

**Ball 🔴 (Update 1.2).** Click flips gravity; unlike Spider it *accelerates* toward the new surface rather than teleporting, giving a near-straight-line path. Click velocities: 3.186G / 3.354G / 3.426G / 3.369G / 3.369G across 0.5×–4×; max fall −15G. Path gets steeper at lower speed. (Informally called "Rollo" by some older community references, but the official name is always Ball.) Dies on hitting the side of a block.

**UFO 🛸 (Update 1.5).** Click hops midair (Flappy-Bird style), full air control. Click velocity is a **constant 7G at every speed portal** — unusual, since most modes vary by speed. Max fall −6.4G. Double-clicking in quick succession gives noticeably more height than spread-out clicks. Dies on hitting the side of a block.

**Wave 〰️ (Update 1.9).** Hold = diagonal up, release = diagonal down; **zero gravity, zero acceleration, zero momentum** — instant direction change. Velocities: ±4.186G / ±5.193G / ±6.457G / ±7.8G / ±9.6G across 0.5×–4×. Normal trail = 45°; mini trail is steeper (~63.43°, a 2:1 slope). Only blue, green, dash, spider, and purple-dash orbs affect it; jump pads/rings do nothing. Dies on contact with any surface (barring special "D" blocks — see Part 4). No extra timing leeway at high speed since nothing about its behavior changes except diagonal steepness.

**Robot 🤖 (Update 2.0).** Hold to jump with height scaling to hold duration; gravity disabled while held. Hold velocities: 5.31G / 5.59G / 5.71G / 5.615G / 5.615G. Max fall −15G. "Micro-clicks" give tiny controlled hops. Dies on hitting the side or bottom of a block.

**Spider 🕷️ (Update 2.1).** Click **instantly teleports** to the nearest surface in the gravity-opposite direction and flips gravity — zero travel time. No air control. Max fall listed as −15G but defined by teleport, not acceleration. Engine mechanic: the small "blue" hitbox searches in the −G direction for the nearest unobstructed solid platform and teleports there in a single tick; if obstructed, it teleports into the obstruction and kills the player — the source of Spider's infamous "died for no visible reason" edge case. Nothing changes with speed portals (teleport is always instant/vertical).

**Swing 🎏 (Update 2.2 — the only new gamemode in 2.2).** Click flips gravity midair with momentum, like a "dual ball"/fan-made Swing Copter — pendulum-like curves, real input-to-response delay. Click behavior: **"multiplies the y-velocity by 0.8 then toggles the gravity"** (identical at every speed portal), max y-velocity −8G, requires 2 ticks held, can click midair. Only the green dash orb flips its gravity (purple dash does not). Gets floatier at higher speed like Ship. Widely considered the hardest mode to design for because of its unresponsiveness; creators often raise the 2.2 Gravity trigger to tighten it.

### 1.5 Gravity flips and portals
A gravity portal flips the direction of "down," preserving vertical velocity but reversing acceleration direction. Cube/Ball/UFO/Robot: arc simply flips. Ship/Swing: disorienting mid-flight because they're momentum modes (2.2's ship consistency fix specifically addressed this). Wave: mirrors cleanly since there's no momentum to disturb. Spider: the flip *is* the whole mechanic. The **2.2 Gravity trigger** sets a player gravity multiplier (documented range 0.10–2.00, and −2.00 to −0.10 for reversed gravity, per HDanke's and GD Creator School's editor docs). There's also a new **Revert portal** (2.2) that flips to the opposite of current gravity.

### 1.6 Mini / size portals
Mini shrinks the icon and changes physics per mode: Cube/Robot get lower jumps and are slightly faster; Ship/UFO have stronger gravity (up/down faster); Ball/Spider fall faster; Wave takes sharper diagonals (~63.43° vs 45°). Hitboxes shrink correspondingly (see Part 3 for exact figures — this is where the numeric documentation actually lives).

### 1.7 Dual mode / dual portals
Two icons respond to the same input simultaneously. By default they have opposite gravity (flipping one flips both) unless 2.2 triggers give each independent gravity. **Documented engine quirk: only Cube and Wave still share gravity between the two icons in a dual; every other gamemode combination has independent gravity** — RobTop simply coded it that way. Crashing either icon kills both (they can't collide with each other). Grid lock: **9 vertical units** by default, or **10 units** if at least one icon is Ship/UFO/Swing/Wave. Dual ships historically fell faster than single ships (long-observed; addressed by 2.2 Legacy Options). Two Balls can't overlap in a dual (Spiders can). No source publishes distinct numeric gravity constants for the two dual icons — treat dual gravity as the standard per-mode constants unless Flip Gravity / Fix Gravity Bug triggers are used.

### 1.8 Speed portals — exact documented values
Community-measured (via move-trigger testing, official Fandom wiki):
- **0.5x:** ~0.807× modifier, ≈8.4 blocks/sec
- **1x:** 1.0× baseline, ≈10.4–11.2 blocks/sec (method-dependent)
- **2x:** ~1.243× modifier, ≈12.9–14.0 blocks/sec
- **3x:** ~1.502× modifier, ≈15.6–16.8 blocks/sec
- **4x:** ~1.849× modifier, ≈19.2–19.6 blocks/sec

The labels are misleading — "2x" is really only ~1.24× baseline, not double. Ratios are more reliable than absolute figures, which carry measurement error across sources.

---

## PART 2 — INPUT BUFFERING

Buffering is registering a held/pre-pressed input slightly before it can take effect, so the action fires the instant it becomes valid. It is a genuine, code-level mechanic, not just a player habit.

### 2.1 The core mechanism
GD Docs states verbatim: "on the second jump of a hold or a buffer click, the gravity is processed before the buffered jump, meaning the player would experience the full jump force on the first tick, which is what causes the common effect of the player jumping slightly higher on the second jump." This is why buffered/held jumps land slightly higher than a fresh single click (see §1.3 tick-ordering quirk).

### 2.2 Ground modes buffer landings; hold modes click midair instead
Cube/Ball/Robot/Spider are **Can Click Midair = No** — they must be grounded to act, so holding through a fall "buffers" the next grounded action and it fires the instant you touch ground. Ship/UFO/Wave/Swing are **Can Click Midair = Yes** — they act on demand in the air, so there is no "hold-before-landing auto-jump" analog for them; only orb-buffering applies (see §2.4).

### 2.3 Buffering per ground mode
- **Cube:** Holding makes the game "continuously check if the player is on the ground to process another jump." Auto-jumps on the first grounded tick. Full velocity table in §1.3.
- **Robot:** Same landing-buffer behavior as Cube; hold also disables gravity and locks a fixed hold velocity. The "Fix Robot Jump" 2.2 editor option exists because "jumping at the right time on a slope or before a pad as a robot would give a massive jump height boost" — a buffering-adjacent edge case.
- **Ball / Spider:** Same grounded-only buffering logic; Spider's click resolves entirely within one tick regardless.

### 2.4 Orb-by-orb buffering behavior
- **Yellow / pink / red orbs (jump orbs):** Fully bufferable — hold before contact, the orb fires the instant you enter its hitbox. Holding is almost always the correct strategy for orb chains.
- **Blue orb (gravity flip):** Bufferable. The classic "blue orb glitch" is a *side effect* of buffering — if you keep holding after the flip, the game auto-jumps off the ground on landing (because you're still holding). Not a bug — buffering working as designed.
- **Green orb (flip + jump):** Bufferable but timing-sensitive; RobTop himself explained the arc timing depends on tap timing ("tap early the arc will start earlier, late will make it start later"). Standard fix: hold beforehand so you hit it at the very start for consistent results.
- **Black orb (downward stomp):** Bufferable; holding through it triggers an auto-jump on landing, so creators place **J-blocks** specifically to disable that follow-up jump (see Part 4).
- **Spider orb (2.2):** Bufferable; instant teleport regardless.
- **Activation / Toggle orbs (2.1): NOT bufferable.** Per the Geometry Dash Creations Wiki: "These Orbs can only be hit if you're not Buffering your input, which means you can't hold pre-emptively to hit these Orbs." The clearest documented buffering *exclusion* among orbs.
- **Dash orbs (green/pink, 2.1):** Held by nature but cut the input after the dash ends — you cannot chain-buffer past a dash orb into the next close orb; a fresh click is required.

For tight orb chains, a single continuous hold only activates the first orb; subsequent ones need a release-and-re-press.

### 2.5 Pads and jump rings
Pads fire automatically on contact, so buffering a pad itself is moot — but holding *through* a pad determines what happens next. You can keep jumping after most pads by holding, **except the spider pad**, which "is the only pad that stops the player from holding the jump button after touching it, acting similarly to a J-block" (dash orbs share this input-cut property).

### 2.6 The "buffer window" — what's actually documented
**No numeric orb buffer window is published anywhere.** The only tick-level figure is GD Docs' **"Ticks Held"** value: **1 tick** for Cube/Ball/Robot/Spider, **2 ticks** for Ship/UFO/Wave/Swing, on the **240 TPS** physics loop 2.2 standardized. Community guides describe orb activation only qualitatively (generous on yellow, tight on pink) with no measured tick count. Treat any specific "the orb buffer window is X frames" claim as unverified.

### 2.7 Buffering changes in 2.2
The one confirmed, sourced change is the **physics-loop standardization to 240 TPS** (December 19, 2023), which altered the absolute tick duration and per-tick acceleration term. Player reports on whether buffering *feel* changed are mixed and largely subjective. No reliable source indicates RobTop changed the underlying buffering *logic* — only the tick rate beneath it.

---

## PART 3 — HITBOXES

### 3.1 How hitboxes work — general mechanics

**Not just two hitboxes.** The player actually carries up to **four simultaneous hitboxes** (per GD Creator School's "Advanced Hitboxes" guide):
1. **Main hitbox (AABB / "red" hazard hitbox)** — exactly 30 units tall and wide for most gamemodes at normal size. Axis-Aligned Bounding Box; collides with non-rotated objects (blocks, upward spikes, slopes); never rotates; kills on hazard contact; carries subframes; also anchors standing-on-top behavior.
2. **Solid hitbox ("blue" / small hitbox)** — a much smaller box nested inside the main one, exclusively for solid-block collision, deliberately small "so that you have more time to react to collisions with solid objects."
3. **Rotated hitbox (OBB)** — an Oriented Bounding Box that collides only with *rotated* hazards. This is why a spike rotated even a fraction of a degree still kills you even though the main AABB no longer registers it. No subframes (expensive math). Its rotation speed is **FPS-dependent**: "high FPS (>=1000) slows down the rotation of this hitbox… most visible on the Ship gamemode… (Due to the 240 fps physics change in GD 2.2 this might become obsolete)." Also responsible for Ball's coyote time.
4. **Slope hitbox** — an inscribed circle within the main hitbox, collides only with slopes/diagonal surfaces, most relevant in Wave; makes certain gaps physically impassable rather than adding difficulty.

**Shape:** hitboxes are predominantly **rectangular/box-shaped** (AABB + inner solid box), plus one oriented rectangle (OBB) for rotated hazards, plus one inscribed circle used only against slopes. They are **not** generally circular.

**Rotation:** the visual sprite tilts constantly, but the **main AABB hitbox stays axis-aligned and does not rotate with the sprite**. Only the OBB hitbox rotates, and only for interactions with rotated *objects* (solid blocks themselves cannot be rotated — only hazards like spikes/saws can be angled).

**Collision resolution / subframes:** the main hitbox checks collisions **4 times per physics tick ("subframes")** to prevent phasing through objects at low FPS — subframes move linearly, not parabolically, across each physics frame. Since 2.2 raised the physics loop to 240 FPS, subframes are largely moot above 240 FPS. The OBB and slope hitboxes have no subframes. X-axis snapping uses the main hitbox's rightmost edge; Y-axis snapping triggers when Y-velocity is zero or points toward the block within a 24-unit offset.

**Practice-mode visualization:** GD has a built-in **"Show Hitboxes"** setting (shows hitboxes in Practice Mode only) plus a **"Disable Player Hitbox"** toggle, and on Steam a quick key: **'P' toggles hitboxes in practice mode.** Hazard hitboxes render red, interactive objects green, solid hitboxes blue. Seeing hitboxes outside Practice Mode requires a mod (Mega Hack / Geode).

**Death timing:** effectively **no meaningful grace period** — contact between player and hazard hitbox on a given (sub)frame is an instant kill; the death animation is purely cosmetic and plays after the kill already registered.

### 3.2 Player hitbox dimensions — every gamemode, normal and mini (well-corroborated, GD Docs)

| Gamemode | Normal blue (solid) | Mini blue | Normal red (hazard) | Mini red |
|----------|------|------|------|------|
| Cube | 9 | 10 | 30 | 18 |
| Ship | 9 | 10 | 30 | 18 |
| Ball | 9 | 10 | 30 | 18 |
| UFO | 9 | 10 | 30 | 18 |
| Wave | 3 | 3 | 10 | 6 |
| Robot | 9 | 10 | 30 | 18 |
| Spider | 9 | 10 | 27.5 | 16.5 (flagged uncertain by GD Docs itself) |
| Swing | 9 | 10 | 30 | 18 |

**The single most counter-intuitive documented fact:** mini mode **shrinks the red hazard box to exactly 0.6×** (30→18; Wave 10→6) but **grows the blue solid box** (9→10) — minis are safer around spikes but very slightly worse at squeezing through solid gaps. Spider's normal red (27.5, ≈0.92 block) is the only sub-30 value among box modes, matching community observation that spider's hitbox runs "slightly smaller… approximately 0.9 blocks." Its mini-red (16.5) is the one player-hitbox figure GD Docs itself marks uncertain.

### 3.3 Hazard and block hitboxes (largely undocumented numerically — qualitative only)

No authoritative source publishes exact hazard hitbox dimensions in units; decompilation repos (lily-pi/GeometryPhysics, camila314/gdp) cover movement math, not hazard geometry. What follows is the best sourced, qualitative picture (primarily GD Creator School's "Static Objects" guide).

**Spikes.** "Their hitbox is rectangular, being elevated around ~¼ of the spike's height" — **not triangular**, a very common misconception (triangular hitboxes belong to slopes, not spikes). The rectangle is narrower/shorter than the visible sprite and raised off the ground, which is why spikes are "smaller than they look." Size variants: **Small Spike ≈ 2/3** of standard, **Mini Spike ≈ 1/2**. Ground spikes "don't follow the same conventions that traditional spikes do." Spikes can be rotated, shifting their collision onto the player's OBB hitbox.

**Saws / spinning blades.** Circular hitbox, "usually extending (approximately) until the teeth" — the visible outer tooth tips extend slightly beyond the actual kill circle. Eight saw variants exist, "these all share different hitboxes between each other." Community-reported (lower-reliability, NamuWiki) quirk: some medium saws have a larger hitbox than large ones, and "the hitbox is not at the end of the blade." Saw-spike hybrids share the circular hitbox but don't auto-rotate.

**Blocks (solids).** "Their hitboxes are always a rectangle, being identical to how they appear visually." Types: Square, Slab, Small Square (½ Square), Small Slab (½ Slab). Kill on side/bottom contact, walkable on top. Some decorative/outline blocks have different hitboxes; vanishing/breakable blocks keep normal collision (fade is cosmetic only).

**Slopes.** Triangular hitbox letting the player slide along the angled top; kills on side/bottom contact like a block. Two types — a 45° slope and a shallower slope, with a **source discrepancy**: one GD Creator School page labels the shallow slope 22.5°, another labels it 26.6° — treat the exact angle as unverified pending an editor check. Slopes cannot be rotated (only warped).

**One-way / thin platforms.** No dedicated object exists; the effect is produced via block **Object Options**: **Passable** ("allows the player to pass through a block from the bottom, but still allows standing on top"), **NoTouch** ("removes the object's hitbox completely"), **Extended Collision** (fixes hitboxes on objects scaled above 6×), **Fix Negative Scale** (addresses shrunken/removed hitboxes from scale hacks) — confirming that scaling an object scales its hitbox, sometimes buggily.

**Orbs and pads (activation hitboxes).** These have an activation/contact zone, not a kill hitbox. Pads trigger automatically on contact; orbs trigger on click/hold while inside the zone — "the orb fires the moment you enter its hitbox," which is exactly why buffering orbs works (Part 2). Activation windows are **not uniform** — described as more forgiving on yellow orbs, tighter on pink — but **exact activation radius in units is undocumented**. Separately well-attested: **lower graphics quality enlarges orb/pad hitboxes** (longstanding community report — "because of medium quality, hitboxes get bigger"), meaning the graphics-quality setting itself can change effective hitbox size.

**On the "85–90% forgiveness" folklore.** The widely repeated claim that spike hitboxes are "~85–90% of visual size" has **no authoritative numeric source**. RobTop has never published a forgiveness percentage, and no dataminer figure surfaced in research. The only real documented "shrink" is the qualitative ~¼-height elevation plus narrower-than-sprite width. Treat any specific percentage figure as unverified community estimate.

### 3.4 Gameplay implications of hitbox size
- **UFO does not have a smaller kill box than Cube** — all box modes (Cube, Ship, Ball, UFO, Robot, Swing) share the identical 30-unit red hazard box. UFO "feeling safer" near spikes comes from its slow, controllable single-tap movement, not a hitbox difference.
- **Wave threads tight gaps** because its 10-unit red box (≈⅓ block) is far smaller than any other normal-size mode.
- **"Mini is safer" is only half true** — smaller kill box, but a *larger* solid box, so minis are marginally worse at squeezing through tight solid gaps even as they're safer around spikes.
- **Rotated spikes can kill "invisibly"** because a spike rotated even slightly moves collision from the AABB to the OBB regime — a documented consequence of the multi-hitbox system, not a bug.
- **Wave "phantom" deaths** trace to the inscribed circular slope hitbox, whose contact is often invisible to the player because none of the box hitboxes appear to touch anything.
- **Documented myths, debunked:** spike hitboxes are triangular (false — rectangular); spikes have "huge" forgiveness (false — modest, ~¼-height elevation); mini shrinks all hitboxes uniformly (false — hazard shrinks, solid grows); hitboxes are identical regardless of graphics settings (false — low/medium quality enlarges orb/pad hitboxes).

---

## PART 4 — SPECIAL BLOCKS (Letter Blocks: S, J, D, H, F)

Since Update 2.1, the level editor's Portal/Pad/Orb tab has included a set of small, unlabeled-in-gameplay objects that the community nicknames **Letter Blocks** — each stamped with a single letter (S, J, D, H, and later F) purely for the *editor* view. **They are invisible during actual gameplay** — the letters exist only so creators can identify them while building. They are **official RobTop-implemented objects** (real object IDs placed like any block), not community hacks or repurposed existing objects — but their exact intended purpose was initially undocumented and had to be reverse-engineered by the community through testing after their 2.1 introduction (a Korean creator group, "2.1 Map Editor Lab," is credited with first working out their behavior).

**Corroboration note:** all five blocks' behaviors below are consistently and independently confirmed across GD Creator School–style community wikis (gdeditor.net's Letter Block page), long-running Steam Community discussion threads, and current community tutorials — treat this as **well-corroborated** community-verified behavior, even though RobTop has never published an official in-game description of them.

### 4.1 J-Block ("Jump Block")
**Function:** Prevents the player's icon from jumping again after clicking/activating an orb. If the player is still holding the input after triggering an orb, the J-block suppresses the automatic follow-up jump that would otherwise fire when the player lands (see Part 2's buffering discussion — this is precisely the mechanic J-blocks are built to counteract). Aside from that jump-prevention, it has no other documented behavior.
**Primary creator use case:** Placed on the ground immediately after a **black orb** (or any orb where the player is expected to keep holding through the interaction) to stop the unwanted auto-jump on landing that buffering would otherwise cause. This is the standard, most-cited use across sources.
**Also affects:** General "disable post-orb jump" scenarios beyond black orbs specifically — any spot where a creator wants to let a held input pass through without triggering a landing jump.

### 4.2 S-Block ("Stop/Dash-Stop Block")
**Function:** Stops/cancels a dash. If an S-block is placed in the path of (or directly over) a **dash orb**, the player still activates the dash orb's initial trigger, but is halted at a minimal distance rather than carrying the full dash momentum through — effectively forcing an abrupt, precise stopping point right after a dash.
**Primary creator use case:** Placed above or after a dash orb when the creator wants the dash *effect* to occur but needs the player to stop immediately afterward rather than sliding the dash's normal full distance — useful for precise, controlled halt points in dash-heavy sections.

### 4.3 D-Block ("Damage Block" / commonly called the "Wave block")
**Function:** Allows the **Wave** gamemode to slide along the top surface of blocks without dying on contact — normally Wave dies instantly touching almost any surface, but a D-block placed in its path lets it ride along the top instead of exploding on impact.
**Primary creator use case:** Building sections where Wave needs to travel along a solid surface (creating "sliding" wave paths), including using chains of D-blocks to legitimately traverse specific level obstacles that would otherwise instantly kill a wave on contact (community example cited: beating the "Sokopon wall" obstacle by riding the wave along a D-block surface rather than avoiding it entirely).
**Community-noted name discrepancy:** some sources informally call this the "Damage Block," but its practical, universally agreed function is enabling Wave-on-block sliding — treat "Damage Block" as a community label for the object rather than a description of what it does (it does not damage/kill the player; if anything it does the opposite by preventing what would normally be a death).

### 4.4 H-Block ("Head Block" / "Bonk Block")
**Function:** Prevents **Cube and Robot** from dying when they jump into the underside or side of a block; instead of the normal "hit the block and die" outcome, the player "bonks" harmlessly off the surface and falls back down without triggering a death.
**Primary creator use case:** Used in tight vertical spaces, jump-training setups, or "jump farm" style sections where creators want the player to be able to test/repeat jump timing against a ceiling/wall without dying on every miscalculated jump; some creators also use it in dual-mode setups for more forgiving jump interactions. Historically (per a 2017-era Steam Community thread), the J-block's jump-prevention behavior was initially thought to be "not working as intended" / possibly buggy shortly after 2.1's release, before the community confirmed its actual intended function through testing — a reminder that these blocks' documented behaviors were established empirically over time, not from an official patch-note description.

### 4.5 F-Block (added later — "Gravity/Surface-Stick Block")
**Function:** The newest of the letter blocks (added after the original S/J/D/H set, not present in the original 2.1 batch). Community testing (via a dedicated "What can you do with the F Block?" community video, cited across sources) converged on two related descriptions: it makes the player **stick to different surfaces** in certain gamemode/orientation combinations (similar to the initial "stick" behavior seen at the start of a dash), and separately, some testers report it affects **gravity-switching behavior on click** in specific setups. **Its exact behavior is the least firmly nailed-down of the five letter blocks** — even dedicated community wiki threads note testers "can't figure out exactly what it does" in full generality, though it is confirmed to be real, placed, and functional (not a placebo object). Community tutorials position it as enabling creative gravity-switching level design (e.g., transition effects between gravity states) — treat this specific block's function as **corroborated in general direction (surface-stick / gravity-interaction) but not precisely/exhaustively documented**.

### 4.6 Summary table

| Block | Nickname | Confirmed function | Typical use | Documentation confidence |
|---|---|---|---|---|
| J | Jump Block | Disables auto-jump after holding through an orb | Placed after black orbs to stop buffered auto-jump | Well-corroborated |
| S | Stop/Dash-Stop Block | Halts player shortly after a dash orb activates | Placed over/after dash orbs for precise stop points | Well-corroborated |
| D | Wave-slide / "Damage" Block | Lets Wave slide on blocks instead of dying on contact | Wave sections riding along solid surfaces | Well-corroborated |
| H | Head/Bonk Block | Cube & Robot bonk instead of dying on block impact | Jump-training setups, forgiving vertical sections | Well-corroborated |
| F | (unnamed) | Surface-stick and/or gravity-interaction on click | Creative gravity-switching transitions | Partially documented — exact mechanics unresolved |

**Important distinction from Part 2's buffering material:** the J-block and the "spider pad stops holding" behavior noted in §2.5 are related but separate mechanics — the spider pad's input-cut is a *built-in* property of that pad object, whereas the J-block is a *separate, deliberately placed* object a creator must add themselves to achieve a similar jump-suppression effect after other orb types (most commonly the black orb).

---

## RECOMMENDATIONS

**For players:**
1. Learn the two physics families first — Wave/Spider are instant and physics-less; everything else has momentum or a true jump arc. This reframes how you read any level.
2. For Ship and Swing, practice anticipation over reaction — "feather" (rapid taps) rather than long holds, especially since both get floatier at higher speed.
3. Exploit buffering deliberately on Cube/Robot/Spider (hold before landing/before an orb) and understand which orbs refuse it (Activation/Toggle orbs, dash orbs, spider pads).
4. Turn on **Show Hitboxes** in Practice Mode (or press 'P' on Steam) to learn true margins before committing to raw attempts — assume zero grace period on any hazard contact.
5. Respect the UFO double-click-height and Robot hold-length quirks — these are the two modes where click *shape*, not just timing, changes outcomes.
6. If a level uses D-blocks with Wave, don't assume Wave will die on contact with that specific surface — check for the sliding behavior before panicking.

**For level designers:**
1. Choose modes by their documented properties: Cube = snappy/versatile; Ship = floaty flow; Ball = delayed flips; UFO = fixed midair pops; Wave = razor precision; Robot = variable holds; Spider = instant snaps; Swing = big curves.
2. Design Swing around arcs, not Ship-style corridors — its unresponsiveness is the #1 reason it's disliked when misapplied; use the Gravity trigger (toward the 2.00 max) for tighter, old-dual-ball-style behavior if desired.
3. Verify dual gravity assumptions — only Cube and Wave share gravity between dual icons by default; everything else is independent in 2.2.
4. Design spike jumps assuming the uniform 30-unit red box across all box modes (not "UFO is more forgiving"), and the 10-unit box for Wave.
5. Avoid rotating spikes by tiny angles unless you specifically want OBB-based "unfair-looking" kills; apply Extended Collision to anything scaled above 6×.
6. Use J-blocks after any orb where the player is expected to keep holding (typically black orbs) to prevent unwanted buffered auto-jumps on landing.
7. Use S-blocks to create controlled, precise stop points after dash orbs instead of relying on level geometry alone to halt dash momentum.
8. Use D-blocks deliberately when you want Wave to survive contact with a surface (sliding sections) — remember this is the exception to Wave's normal "dies on any contact" rule.
9. Consider H-blocks for practice-friendly or intentionally forgiving jump-timing sections with Cube/Robot.
10. Treat F-blocks as experimental/advanced — test thoroughly in the editor before relying on them, since their behavior is the least fully documented of the letter blocks.

---

## CAVEATS AND OPEN GAPS

- **Ship's exact hold/release acceleration is genuinely unresolved.** GD Docs itself calls ship "not fully understood" and leaves its per-speed hold/release rows blank; the −25 blocks/s² figure is a single-source community estimate (lily-pi/GeometryPhysics), not a verified engine constant.
- **No numeric orb/hazard buffer window or hazard hitbox dimensions exist in any accessible source.** Ticks Held (1 or 2, per mode) is the only documented tick-level granularity; anything more specific circulating in videos or Discords is unverified.
- **Mini's per-gamemode physics multiplier (beyond hitbox scale) is undocumented** — the 0.6× red-hitbox figure is solid, but jump/gravity "feel" differences are described only qualitatively.
- **Legacy Options vs 2.2 ship gravity exact old/new numeric values are unpublished** — only the change's existence and date (December 19, 2023, tied to the 240 TPS standardization) are confirmed.
- **Dual-mode gravity constants are not separately documented** — treat dual gravity as identical to single-icon constants unless Flip Gravity/Fix Gravity Bug triggers are in play.
- **Spider's mini-red hitbox value (16.5) is flagged uncertain by GD Docs itself** — the only player-hitbox figure in the whole table without full confidence.
- **The 22.5° vs 26.6° shallow-slope angle discrepancy** between two GD Creator School pages is unresolved; verify against the live editor if precision matters.
- **The "85–90% spike forgiveness" percentage is folklore with no primary source** — do not cite it as fact.
- **The F-block's exact function is the least firmly documented of the five letter blocks** — community testers converge on "surface-stick and/or gravity-interaction" but no source gives a precise, exhaustive mechanical description. None of the letter blocks (S, J, D, H, F) have ever received an official RobTop-written description; all documented behavior comes from community reverse-engineering/testing after their editor release.
- Community secondary sources (NamuWiki, general "GD guide" sites, TikTok tutorial summaries) were used only for qualitative, lower-stakes claims and are flagged inline wherever used; all numeric physics and hitbox constants are sourced to GD Docs (boomlings.dev) and cross-checked against GD Creator School wherever possible.
- All figures reflect **Update 2.2** (2.2074/2.2-era, 240 TPS physics standard). If RobTop releases 2.3, re-verify the "exactly eight gamemodes" claim and the ship/mini physics gaps noted above.

---

*Primary sources: GD Docs (boomlings.dev) — player_physics/gamemodes and player_physics/hitboxes pages; GD Creator School (gdcreatorschool.com) — Using Gamemodes, Advanced Hitboxes, Static Objects, Gameplay Objects, Editor Settings guides; the Official Geometry Dash Wiki (geometrydash.wiki.gg) and Fandom wiki; gdeditor.net's Letter Block reference page; lily-pi/GeometryPhysics and camila314/gdp GitHub decompilation repositories; community forum/wiki move-trigger and hitbox-testing discussions (Steam Community, r/geometrydash, NamuWiki, community tutorial videos — flagged as lower-reliability where used).*
