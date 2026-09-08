# The Geometry Dash Level Editor: A Complete Reference (v2.2 / 2.2+)

*A friendly, thorough guide to everything the editor can do — plus a sourced roundup of what the community wishes it did better. Current as of September 2026.*

---

## TL;DR

- **The 2.2 editor is the biggest creative overhaul in Geometry Dash history:** released on 19 December 2023 on Steam and 20 December 2023 on Android and iOS, it added 86 new triggers, a full camera-control system, post-processing shaders, a keyframe animation system, item/counter logic triggers, an in-game Music Library and a massive SFX library, a particle editor, and removed the old object cap — turning the editor from a "level maker" into something closer to a game engine.
- **The most common community complaints are consistent and well-documented:** a brutal learning curve worsened by missing/placeholder in-editor help text, editor lag with high object counts (especially on mobile), no native online collaboration (people pay for third-party mods), weak object search/multi-edit, and a mobile editor that lags behind PC.
- **RobTop has confirmed more is coming** (custom keybinds, an upgraded auto-build UI, Versus mode, "The Map," Swing/Wave in platformer for 2.3) but also said 2.2 is "already too much" and he won't add new features to it — with 2.21 still unreleased and no firm public date as of early-mid 2026.

---

# PART 1 — Editor Features (Comprehensive List)

## 1. The Basics: How the Editor Works

The Geometry Dash editor is where you build custom levels by placing objects on a grid while a song plays. You can then playtest, save, and (with a verified full run) upload for others to play.

**Build Mode vs. Edit/Play:** The editor has tabs at the bottom. **Build mode** is where you pick and place objects. **Edit mode** lets you select, move, rotate, scale, and delete placed objects. **Delete mode** removes them. You can playtest at any time from inside the editor, and 2.2 added an option to slow down in-editor playtesting.

**Moving around:** You navigate by swiping/dragging (the "free move" / swipe controls), and you can zoom the camera in and out. In 2.1, RobTop's 2.11 patch notes confirm the editor zoom range was widened — "Max editor zoom: 1.5 → 2.0" and "Min editor zoom: 0.3 → 0.2."

**Precision placement:** Objects snap to a grid by default (1 grid cell = 30 units; triggers and sliders often work in tenths, where 1 cell = 10 "steps"). You can nudge selected objects with arrow keys for fine positioning, free-rotate them, and stretch/scale them. Copy, paste, and copy-paste with offsets are all supported, as is "linking" objects (introduced in 2.1) so they're always selected/deleted together as one unit.

## 2. Object Categories

Objects are organized into tabs. The main categories:

- **Blocks (solid/collision):** The floors, walls, and platforms you land on or die against. Includes basic solid blocks, slopes, and thousands of decorative block designs. 2.2 added "Auto-Build," which automatically builds outlines, corners, edges, and tiles around your block designs to speed up detailing, plus over 1,000 new pixel-art blocks and pickup objects.
- **Spikes / hazards:** Objects that kill the player on contact.
- **Special blocks (gameplay-modifying):** These change how the game behaves. Examples include the **"S" block** (stops orb/pad buffering), **"H" block** (removes damage from above), **"D" block** (lets the wave pass through), **"J" block** (changes jump behavior), and **"F" block** (changes gravity). 2.2 also added a **"Passable" block option** (jump through a solid from below, land on top) and the **Force Block**, which pushes the player when touched (Y-axis in normal mode, also X-axis in platformer).
- **Orbs:** Tap-activated rings that give a jump/boost in mid-air (yellow, pink, red, blue, green, black, spider, dash, and more). 2.2 added the **purple gravity-reversal orb**.
- **Pads:** Like orbs but activate automatically when touched (yellow, pink, red, blue, spider). 2.2 added the **purple gravity pad**.
- **Portals:** Change the player's state. **Game-mode portals** switch between cube, ship, ball, UFO, wave, robot, spider, and (new in 2.2) **swing**. Other portals change **gravity** (including a new green gravity-reverse portal), **size** (mini/big), **speed** (slow → very fast), **dual** (two players at once), **mirror**, and **teleport** (which in 2.2 can be unlinked to teleport along the X-axis).
- **Decorations:** Non-solid visual objects — the huge library of designs, glow, pulse-able art, animated objects, and pixel art used to make levels look good.
- **Text/letter objects, particles, and animated objects:** 2.2 hugely expanded animated objects (monsters, machinery) with an "Edit Special" menu for controlling animation speed, randomized start, etc.

## 3. Game Modes You Can Switch Between (via portals)

Each mode controls completely differently, and switching is done with portals mid-level:
- **Cube** – jumps.
- **Ship** – flappy-bird-style flight.
- **Ball** – tap to switch gravity, rolls along surfaces.
- **UFO** – tap for small flappy hops.
- **Wave** – hold to go up, release to go down, sharp diagonal movement.
- **Robot** – variable-height jump (hold to jump higher).
- **Spider** – instantly teleports between floor and ceiling.
- **Swing** (new in 2.2) – swingcopter-style, gravity flips each tap.

**Platformer Mode (new in 2.2):** A separate level type where the player moves left/right freely instead of auto-scrolling. It has its own physics, placeable checkpoints, downward-slope sliding, and rewards **Moons** instead of Stars.

## 4. The Trigger System (the heart of the modern editor)

**What a trigger is (plain English):** A trigger is an invisible object that makes something happen when the player reaches it — move a wall, change a color, play a sound, shake the screen, spawn other triggers, and so on. Triggers are found on their own tab. As of 2.2 there are roughly 130+ distinct trigger types.

**Key trigger concepts:**
- **Group IDs:** You tag objects with a numeric Group ID (up to 9,999 groups in 2.2), and triggers act on whichever group you point them at. This is how a Move trigger knows *which* objects to move.
- **Color channels:** Colors are stored in numbered "channels" (up to 999). Change a channel's color and every object using it updates at once. 2.0 introduced effectively unlimited color channels; 2.2 added RGB and HEX code input.
- **Easing:** A smoothing option (ease in, ease out, ease in-out, elastic, bounce, etc.) so movements/animations accelerate and decelerate naturally instead of moving robotically.
- **Spawn-triggered / Touch-triggered / Multi-activate:** Most triggers can be set to fire only when *spawned* by another trigger, only when the player *touches* their hitbox, and/or to fire more than once.

**The main trigger families:**

*Movement & transformation:*
- **Move** – moves a group along X/Y (2.2 can lock the camera to X or Y, or move toward another object's position).
- **Rotate** – spins a group around itself or another point.
- **Scale** (new in 2.2) – resizes a group, optionally on one axis, with stretch/deform.
- **Follow** – makes a group follow another group or the player.
- **Advanced Follow / Edit Advanced Follow / Re-Target** (new in 2.2) – physics-based following with momentum/friction.
- **Follow Player Y** – matches the player's vertical position.
- **Keyframe system** (new in 2.2) – a proper animation tool: you place keyframe objects (positions/rotations/scales), link them into an "animation," and a group smoothly transitions between them. Effectively Move + Rotate + Scale combined, with per-keyframe easing and timing modes (Time/Even/Dist). Edited via a dedicated keyframe editor.

*Color & visual:*
- **Color** – changes a color channel (with fade time).
- **Pulse** – briefly flashes a color/HSV shift then reverts (great for rhythmic beats).
- **Alpha** – changes transparency of a group (2.2 lets you type in exact fade time and alpha values).
- **Gradient** (new in 2.2) – draws a customizable color gradient across an area; widely called one of the most powerful new visual triggers.

*Camera (all new in 2.2 — the single biggest visual leap):*
- **Zoom** – dollies the camera in/out.
- **Static** – locks the camera onto a specific object (for cutscenes).
- **Offset** – shifts the camera position.
- **Rotate (camera)** – spins the whole view.
- **Edge** – limits how far the camera can travel.
- **Guide** – smooths camera follow in platformer mode.
- **Mode / Gameplay Offset** – changes where the player sits relative to the camera.

*Screen effects / shaders (new in 2.2):* Shock Wave, Shock Line, Chromatic, Chromatic Glitch, Pixelate, Lens Circle, Radial Blur, Motion Blur, Bulge, Pinch, Grayscale, Sepia, Invert Color, Hue, Edit Color, and Split Screen. These are post-processing effects applied over the whole screen.

*Logic, spawning & control:*
- **Spawn** – fires another group (of triggers) after a set delay; the backbone of complex levels. 2.2 gave it a new interface and options.
- **Toggle** – turns a group on/off.
- **Stop** – halts an active trigger/group.
- **Sequence** (new in 2.2) – runs multiple groups in order.
- **Spawn Particle / Reset / Instant** helpers.

*Randomization (new in 2.2):*
- **Random** – activates one of two groups at random.
- **Advanced Random (AdvRand)** – picks among many groups with weightings, so levels can play differently each attempt. (RobTop later showed an improved "better random trigger" supporting more than two groups.)

*Collision & input:*
- **Collision** – fires when two "collision blocks" (Block A/B) overlap; in 2.2 the player itself can be Block A/B (shown as "P").
- **Instant Collision** – checks collision on a single frame.
- **Collision State** – tracks entering/exiting an area.
- **Touch** – fires on tap/click.
- **On Death** – fires when the player dies.
- **Area triggers** (new in 2.2) – Area Move/Rotate/Scale/Tint/Fade, etc., affecting objects within a radius of a target for wave-like mass effects.

*Item / counter / timer system (new/expanded in 2.2) — turns the editor into a mini programming environment:*
- **Item / Pickup** – grants or removes points/counter values (override count option added).
- **Count / Instant Count** – checks how many of an item ID exist and reacts.
- **Item Edit** – performs math (add, subtract, multiply, divide) on stored values.
- **Item Comp** – compares values (logic checks / conditionals).
- **Item Pers** – persistent storage that survives across attempts.
- **Timer / Time / Time Event / Control** – create and manage on-screen or hidden timers, useful for platformer challenges and estimated completion times.
- **Item Counter object** – displays a live number on screen (attempts, points, timers).

*Player & gameplay modifiers (new in 2.2):*
- **Reverse** – makes the player travel backwards.
- **Gravity** – changes gravity strength on the player.
- **Arrow** – changes direction of gravity/movement mid-level.
- **TimeWarp** – speeds up or slows the whole level's time (RobTop stated a range of about 0.1x to 2.0x), not just the player.
- **Player Control** – controls the player directly.
- **Options** – toggles things like Hide P1/P2, disable background, hide/show ground, wave-streak blending, etc.
- **End** – ends the level on activation (with options for restart position, etc.).
- **Event / Event-Link** – links "player events" (jump, land, orb-jump, robot-jump, die, collect item) to a group, so triggers fire in response to what the *player* does rather than a fixed spot on the timeline.

*Audio (new in 2.2):*
- **Song trigger** – load and start a song (from Newgrounds ID, the Music Library, or NCS library) mid-level; set start/end timestamps, fade in/out, volume, pitch (per-semitone), and looping. You can layer/change songs during a level for the first time. (Per RobTop's official FAQ, a single level can use a maximum of 20 songs.)
- **Edit Song** – change volume/pitch/proximity of an already-playing song. Includes **proximity** (volume changes with distance from the player, camera, or an object).
- **SFX trigger** – play from a large library of sound effects (the game's SFX Library contains well over 13,000 sounds, organized by category and searchable), with unique SFX IDs, groups, fade, pitch, and proximity. Per RobTop's official FAQ, the per-level SFX limit is 1,000.
- **Edit SFX** – modify playing sound effects.

## 5. Editor Tools & UI Features

- **Editor Layers:** Separate organizational "layers" you can sort objects into and view/edit in isolation. Includes **Layer Locking** (prevents accidental selection/deletion of a layer).
- **Select Filter & Select All:** "Select Filter" (toggled in the pause menu) lets you select only objects with chosen attributes; "Select All" grabs everything on the current editor layer, with left/right-of-center variants.
- **Edit Group (Group IDs), Edit Object, Edit Special:** Menus for assigning groups and configuring object-specific behavior.
- **Free Scale / new scale system (2.2):** Scale objects as a whole, per-axis, or stretch/deform.
- **Copy/Paste, Copy Values, Paste Color, Paste State.**
- **"Create Loop" tool (2.2):** In the menu tab, helps build repeating trigger loops.
- **Particle Editor (2.2):** Design custom particle effects (sparks, smoke, etc.) with many parameters — described by RobTop's camp as more optimized than the old method of spamming objects.
- **Reset unused color channels, HSV editing, and RGB/HEX color input.**
- **Dynamic Height (2.2):** Raises the vertical building limit.
- **Object limit removed (2.2):** The Official Geometry Dash Wiki confirms the setting is now "40,000, 80,000, and Infinite. Levels with more than 80,000 objects will display a second icon and a warning," with a max upload file size to keep levels manageable, and "Max groups increased to 9,999." In 2.1 the old 80,000 cap required hacks/mods to exceed.
- **Extras tab (2.2):** Options like "Don't fade," "Don't Enter," "Group Parent," etc.
- **Rows/columns customization** for the build/edit button layout.

## 6. Song & SFX Features

- **Song selection:** Pick from the game's main songs, a Newgrounds song ID, the in-game **Music Library** (thousands of curated songs), or the **NCS (NoCopyrightSounds) library** — added in the 2.206 update, which the Official Geometry Dash Wiki dates to 2 June 2024 (the Fandom wiki lists 1 June) and describes as "NCS added to Music Library. (1200+ songs)." RobTop curates the Music Library manually by contacting artists and, per his official FAQ, "does not take requests to be added here."
- **NONG ("Not On Newgrounds"):** Songs not available on Newgrounds, historically swapped in via game files or third-party tools/mods (e.g., the Jukebox Geode mod). This has long been a manual hassle.
- **In-level music/SFX:** As above, the Song, Edit Song, SFX, and Edit SFX triggers (2.2) allow dynamic music and immersive, proximity-based sound.

## 7. Level Settings

From the level settings/pause menu you can set: the **song**; **background** (39 new in 2.2) and **ground** (5 new) designs; ground/background base colors; the level's starting game mode, speed, mini/dual state (via a Start Position); **background color and gradient ground**; level name/description; difficulty suggestion; and enable options like "Ignore Damage" (2.206) or hiding the completion screen. You place **Start Position** objects to test from any point. Level length is determined by how far your objects extend (Tiny → XL, plus Platformer).

## 8. Collaboration & Sharing

- **Native sharing:** Upload finished levels to the servers; mark as **unlisted** (only findable by ID); organize with **folders**; and (2.2) create **Lists** — collections of levels any user can assemble (developer-approved Lists reward diamonds).
- **Collabs, the old-fashioned way:** GD has **no built-in real-time collaboration.** Traditionally, collaborators build parts separately and pass a copyable level around, or one person stitches parts together. Real-time collaborative editing exists only via **third-party Geode mods** (see Part 2).

## 9. Recently Added / Post-2.2 Updates

2.2 has received many small updates (2.201–2.208, plus 2.2071–2.2081). Notable editor-relevant additions:
- **2.206** (2 June 2024 on Steam/Android/iOS per the official wiki): NCS library added; "Ignore Damage" in editor levels; hide Level Complete screen; estimated completion time for platformer.
- **2.207** (Nov 2024): Event Levels and chests; new song trigger options.
- RobTop showed an improved/"better random trigger" (May 2024) supporting more than two groups.
- **2.208** (updated to Steam on 19 January 2026 and Android/iOS on 30 January 2026 per the official wiki), which added a "Click Between / On Steps" option and the returning Lite level "Electroman Adventures," plus further minor patches.
- **Update 2.21 (upcoming, no confirmed public date as of early-mid 2026):** will fold in delayed 2.2 features — **Versus mode**, **The Map** (user-made platformer levels, Demon Towers, rewards), the **Explorers** level, plus **custom keybinds** and an **upgraded UI for 2.2 editor features like auto-build**.

---

# PART 2 — Community Complaints & Wishlist Items

*These are community opinions and are attributed to where they were found. They are not presented as fact but as documented sentiment.*

## A. The Learning Curve & Missing In-Editor Help

This is the single most repeated editor complaint after 2.2.

- **Placeholder / joke help text.** The official and Fandom GD wikis' "Triggers" articles document that many triggers shipped with unfinished or joke placeholder help text (e.g., "X trigger help," and a JoJo's Bizarre Adventure "Za Warudo" gag in the TimeWarp trigger). Historically RobTop compensated by building example levels ("Editor Examples 002/003") instead of writing real help. *(Source: Geometry Dash Wiki, "Triggers," geometrydash.wiki.gg and geometry-dash.fandom.com.)*
- **"Holy hell is it underwhelming. WHY IS THERE BARELY ANY EXPLANATIONS FOR WHAT EACH THING DOES!?"** — a community post on the Fandom forum ("My opinion on 2.2"), which also argues the lack of explanations widens the gap between good and new creators and risks discouraging beginners. *(Source: geometry-dash.fandom.com/f/p/... "My opinion on 2.2.")*
- The community had to write its own manual: the **official-endorsed 2.2 Editor Guide by Viprin and AutoNick** (~200 pages, hosted on robtopgames.com), distributed because "learning everything yourself is a near impossible task given the size of the editor as of update 2.2." *(Source: Steam Community Guide "Geometry Dash 2.2 Editor Guide.")*
- Even top creators find the native trigger workflow inadequate: **Spu7Nix built an entire external programming language, SPWN**, whose GitHub README states it "compiles to Geometry Dash levels... This is especially useful for using GD triggers, which (if you want to make complicated stuff) are not really suited for the graphical workflow of the in-game editor." *(Source: Spu7Nix, SPWN-language, github.com/Spu7Nix/SPWN-language.)*

## B. Editor Lag & Performance

- Lag with high object counts is a long-running complaint, especially on mobile and even high-end PCs. Steam threads note levels like "Back on Track usually lags a lot due to high object count," and users report that heavily detailed levels can be "practically unplayable, even with a high-end pc." *(Source: Steam Community GD discussions.)*
- Multiple users specifically report **editor lag** — e.g., a GD forum thread describing everything in the editor happening "at an about 3 second delay," and another noting the editor lags with ~4,000 objects but the saved level plays fine. *(Source: gdforum.freeforums.net "Laggy editor" and "need this to fix" threads.)*
- A widely shared critique argues 2.2's removal of the object cap led creators to add "so many unnecessary objects that were lagging some old mobile devices," and that GD "just doesn't feel like its own game anymore, it feels like a game engine." *(Source: Medium, theGenius9, "Why the 2.2 update in Geometry Dash broke the game.")*
- Community/technical writers note GD runs on RobTop's custom engine that assumes consistent frame delivery, so a single dropped frame can desync input — meaning raw hardware power doesn't guarantee smooth performance. *(Source: playgeometrydash.com — note: this is a fan/aggregator blog, treat as opinion.)*

## C. Object Search, Selection & Multi-Editing

- **Selecting a specific object or "all of one type" is unintuitive.** Steam threads show users struggling to select all of a particular object, with the workaround buried in the pause menu (Select Filter → Delete tab → Custom). The Select Filter setting also silently breaks selection/deletion, confusing users "for years." *(Source: Steam Community, "How to select all of a particular object in the editor?" and multiple select-filter threads.)*
- **Multi-editing limitations.** The community-run GD Editor wiki documents that when multiple objects are selected, "Edit Special" lights up but often won't open, and that numeric entry for trigger values is limited by text length (a negative sign or decimal costs a digit of precision). *(Source: gdeditor.net, "Potential issues.")*
- Wishlist staples on the GD forum "quality of life" thread include high-quality mobile textures and various small editor conveniences. *(Source: gdforum.freeforums.net, "What quality of life features does Geometry Dash need?")*

## D. Mobile Editor Limitations

- Consensus across Steam threads: **creating on PC is far easier** thanks to mouse precision and keyboard shortcuts, while "creating levels are easier on mobile" is a minority view; most say mobile risks "exploding your phone" on detailed levels and lacks the speed-up keybinds PC enjoys. *(Source: Steam Community, "I have this game on mobile, should I get it on PC?" and related.)*
- **Custom keybinds don't fully exist yet** and are a tracked upcoming feature for 2.21 — implicit acknowledgment of the current gap. *(Source: Geometry Dash Wiki, "Update 2.21.")*

## E. No Native Collaboration

- GD has no built-in real-time collaboration, so creators rely on the paid third-party Geode mod **Editor Collab by alk1m123** ("the ultimate live multiplayer editor collaboration tool"), where hosting requires a paid key. *(Source: geode-sdk.org/mods/alk.editor-collab; editorcollab.com.)* The gap is visible in Steam threads where users hunt for a working "editor collab mod." *(Source: Steam Community, "editor collab mod.")*

## F. Requested Triggers / Object Behaviors That Don't Exist Yet

- **A "Z-layer" / Z-order trigger** to move objects between draw layers via trigger. When asked, RobTop reportedly said it "would be easy to add but will likely not be in 2.2." Still not a native trigger. *(Source: Geometry Dash Wiki, Update 2.2 dev timeline, citing RobTop's Discord.)*
- Requests for deeper randomization were partially answered — RobTop later showed a "better random trigger" supporting more than two groups. *(Source: GD Wiki, Update 2.2 timeline.)*

## G. Comparison to Other Editors (Mario Maker, etc.)

- The community frequently frames GD's editor as vastly more powerful but far less accessible than Nintendo's Super Mario Maker — GD offers near-limitless scripting (people rebuild Tetris and other games inside it) at the cost of a punishing learning curve, whereas Mario Maker is beginner-friendly but constrained. Video essays and streams directly pit the two against each other (e.g., "Geometry Dash 2.2 Is Better Than Mario Maker," and "Level Creator Showdown: SMM2 vs Geometry Dash"). A recurring meta-complaint (theGenius9 Medium piece) is that GD has become "a game engine" rather than a focused level maker. *(Sources: YouTube video titles; Medium.)*

## H. Removed / Changed Things the Community Reacted To

- **Everyplay replay support was removed in 2.2** with no built-in replacement (RobTop said an alternative was unlikely soon due to stability issues). *(Source: GD Wiki, Update 2.2.)*
- **On Steam, the editor's "Create" button was removed** — RobTop clarified the editor remains but is intended to be used through the app for a better experience; this initially alarmed players. *(Source: toolify.ai summary of 2.2 changes — treat as secondary.)*
- The **Shake trigger** was reworked/expanded relative to older behavior (early reaction: "Rip Shake Trigger"). *(Source: Fandom forum, "Update 2.2 New Triggers + blocks revealed.")*

## I. What RobTop Has Said About the Future

- **"2.2 is already too much"** — RobTop said he would add no further *new features* to 2.2, but is accepting suggestions for 2.3. *(Source: GD Wiki, Update 2.2, citing RobTop.)*
- **Confirmed/tracked for 2.21:** Versus mode, The Map, Explorers level, **custom keybinds**, and an **upgraded UI for 2.2 editor features like auto-build.** No confirmed public release date as of early-mid 2026. *(Source: GD Wiki, Update 2.21.)*
- **Confirmed for 2.3:** Swing and Wave forms accessible in platformer mode ("though he does have better plans for them"). *(Source: GD Wiki, Update 2.2.)*
- **Camera-angle manipulation trigger** was revealed as a plan during development and largely realized through the 2.2 camera trigger suite. *(Source: GD Wiki, Update 2.2 timeline.)*

---

# Recommendations (for a creator getting the most out of the editor)

1. **Start with the "core five" triggers before anything fancy:** Move, Spawn, Toggle, Color, and Rotate. Almost every modern level is built on these; the camera and shader triggers are far easier once these click.
2. **Use the community manual, not the in-game help.** Because in-editor help text is incomplete, download the Viprin/AutoNick 2.2 Editor Guide (hosted on robtopgames.com) and lean on GD Creator School (gdcreatorschool.com) for trigger-by-trigger walkthroughs.
3. **Manage performance proactively:** Use editor layers + layer locking, keep object counts reasonable on sections meant to run on mobile, prefer the particle editor over object-spam for effects, and use "Low Detail Mode"-friendly design if you want wide device support. If your editor itself lags, split work across layers and test saves frequently.
4. **For collaboration,** decide up front: for casual splits, use the copy-a-level pass-around method; for real-time co-editing, budget for the paid Editor Collab Geode mod (PC/Geode only) and confirm all collaborators can run Geode.
5. **For music,** prefer the in-game Music Library or NCS library for hassle-free, YouTube-safe audio; only go the NONG route (with a mod like Jukebox) when a specific track isn't available, and always credit artists. Remember the per-level caps (20 songs, 1,000 SFX).
6. **Watch the update channel.** If custom keybinds and the auto-build UI upgrade land in 2.21, revisit your mobile/keybind workflow — those directly target today's biggest QoL gaps.

**Benchmarks that would change this advice:** If 2.21/2.3 ships native collaboration, an improved help/tutorial system, or a native NONG manager, drop the third-party workarounds above. If RobTop ships a Z-layer trigger or multi-value trigger editing, revise the "work around selection/multi-edit limits" guidance.

# Caveats

- **Version fluidity:** 2.2 has had many minor patches (2.201–2.208 and beyond) and 2.21 is unreleased with no firm public date as of early-mid 2026; some "confirmed" future features are sourced from RobTop's Discord/Twitter as logged by the community wikis, not formal announcements, and could change.
- **Source quality:** The feature list draws on the official GD wikis, RobTop's own site/FAQ, and detailed creator guides. The complaints section mixes primary community sources (Steam, GD forums, GitHub, wikis citing RobTop) with some fan-blog and video-title evidence; where a source is an aggregator/blog or a single user's opinion, that's noted. Direct r/geometrydash thread quotes were hard to retrieve in-tool, so some Reddit-origin sentiment is represented via other community venues.
- **Numbers vary by source:** Trigger counts (86 "new" in 2.2; ~130+ total), song/SFX library sizes, and object/group caps are cited as the community/wiki consensus figures and may be refined in later patches. Minor date discrepancies exist between the two main wikis (e.g., 2.206's release is dated 2 June 2024 on wiki.gg vs. 1 June on Fandom).

---

# PART 3 — Default Sprite Links (Official Wiki Image Categories)

These link to wiki pages hosting the actual default (non-custom-texture) sprite files for each category. Each category page lists every individual PNG with a thumbnail and a direct file link — click through from there to grab the full-resolution image.

**Spike (default):**
- Spike images (official wiki) — includes the base `RegularSpike01–04.png` set (the plain default spike at full size, half-width, three-quarter, and small variants), plus outline, fake-spike, and colour-overlay versions: https://geometrydash.wiki.gg/wiki/Category:Spike_images
- Mirror on Fandom (same file set): https://geometry-dash.fandom.com/wiki/Category:Spike_images

**Gamemodes (icon kit — cube, ship, ball, UFO, wave, robot, spider, swing, jetpack):**
- Full Icon Kit image category (all gamemodes' icon sprites, one sub-category each): https://geometry-dash.fandom.com/wiki/Category:Icon_Kit_images
- Individual sub-categories if you want just one mode (append each to `https://geometry-dash.fandom.com`): Cube — `/wiki/Category:Cube_icon_images`; Ship — `/wiki/Category:Ship_icon_images`; Ball — `/wiki/Category:Ball_icon_images`; UFO — `/wiki/Category:UFO_icon_images`; Wave — `/wiki/Category:Wave_icon_images`; Robot — `/wiki/Category:Robot_icon_images`; Spider — `/wiki/Category:Spider_icon_images`; Swing — `/wiki/Category:Swing_icon_images`; Jetpack — `/wiki/Category:Jetpack_icon_images`
- Portals page showing each gamemode's in-level portal sprite side by side (Cube/Ship/Ball/UFO/Wave/Robot/Spider/Swing portals): https://geometry-dash.fandom.com/wiki/Portals

**Blocks & Slabs (default):**
- Block images category (default block tilesets, before custom texture packs): https://geometry-dash.fandom.com/wiki/Category:Block_images
- Note per the community wiki's object-type guide: "blocks" are the square objects and "slabs" are the shorter, half-height ones — both live in the same first Build-tab category, with slabs positioned near the end of the block-tab pages in the 2.2 editor: https://www.gdcreatorschool.com/docs/guides/the-editor/object-types/

**Portals (all types):**
- Portal images category — every portal sprite (Ball, Cube, Ship, UFO, Wave, Robot, Spider, Swing portals; Dual A/B; Gravity A/B/C; Mirror A/B; Size, Speed, and Teleport portals), 35 files total, each with a plain and "Labelled" (with icon overlay) version: https://geometry-dash.fandom.com/wiki/Category:Portal_images
- Portals main article (organized by category — gamemode, gravity, dual, mirror, mini/size, speed — with each sprite shown inline and explained): https://geometry-dash.fandom.com/wiki/Portals

---

# PART 4 — Most Important Features (Quick-Reference List)

If you only remember ten things about the modern (2.2) editor, make it these — they're the features that do the most creative heavy lifting:

1. **Groups + the Move/Rotate/Scale/Keyframe triggers** — the foundation of all custom animation. Tag objects with a Group ID, then control them with these triggers (or chain them into a full keyframe animation).
2. **Spawn trigger** — fires other groups after a delay; this is how virtually every complex sequence in a modern level is built (it's the "glue" trigger).
3. **Camera triggers (Zoom, Static, Offset, Rotate, Edge, Guide)** — 2.2's single biggest addition; lets you direct the player's view like a film camera instead of a fixed side-scroll.
4. **Color channels + Color/Pulse/Gradient triggers** — unlimited numbered channels mean you can restyle an entire level by changing one channel, and Gradient in particular is prized for how much visual polish it adds fast.
5. **Item/Counter/Timer system (Item, Item Edit, Item Comp, Count, Timer)** — turns the editor into a lightweight programming environment: conditionals, math, persistent values, and on-screen counters.
6. **Song & SFX triggers** — dynamic, in-level music/sound changes (proximity, pitch, fade) instead of one static track — plus the Music Library/NCS library for hassle-free licensing.
7. **Auto-Build** — automatically generates outlines/corners/tiling around your block designs; the single biggest time-saver for detailing.
8. **Editor Layers + Layer Locking** — essential for organizing complex levels and preventing accidental edits, especially once object counts get high.
9. **Object cap effectively removed (up to 80,000 / Infinite) + 9,999 groups** — freed creators from the old hard ceilings, though it's also the direct cause of today's lag complaints (see Part 2B).
10. **Platformer mode** — a whole second way to build/play levels (free left-right movement, checkpoints, Moons instead of Stars) rather than the traditional auto-scroll format.
