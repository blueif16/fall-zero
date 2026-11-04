---
name: tip-over
description: How Fall 0 surveys a room photo for anything that can tip or fall onto a person, describes each piece so the physics engine can test it, and judges from safety guidance what the engine can't build.
---

# Tip-over check

People photograph a room: a nursery, a kitchen, a garage, a grandparent's bedroom. Your job is to find
everything free-standing that could tip, fall or be pulled over onto someone, and hand each piece on
in a form the next step can use. A physics engine tests most furniture by building it from a short
description. For anything it can't build, you judge the risk yourself from the references.

Three risks matter for every piece:
- **child**: a child climbs it, hangs on an open door or drawer, or pulls on it;
- **adult**: an adult, often an older person, grabs or leans on it for balance;
- **quake**: the floor shakes in an earthquake and the piece, or what stands on it, falls.

## Survey

List every free-standing thing in the photo that could tip or fall onto a person. Include:
- case furniture: dressers, chests, wardrobes, bookcases, shelving units, cabinets, hutches, media
  units, filing cabinets, tool chests, shoe cabinets, linen towers;
- appliances that can tip: freestanding ranges, stacked washer-dryers, microwave carts;
- screens and other things that topple: a TV standing on its own, leaning floor mirrors, tall
  floor lamps, coat racks, gun safes, heavy tall decor.

Leave out what can't tip: built-in or wall-hung kitchen cabinets, beds, sofas, tables, chairs, and
anything already fixed to the wall.

Everything standing on a piece goes in that piece's `on_it`, never as a piece of its own: every separate
thing on its top or on its open shelves, such as a TV, a lamp, a plant, a basket, a toy, a vase, a
speaker, a box, or a stack of books lying flat. Each thing gets its own entry; a stack of boxes is one
entry. Rows of books, folded clothes or dishes filling a shelf are that shelf's contents (the Describe
step counts them), not things on it. Things behind doors or inside drawers are contents too.

For each piece:
- `name`: a few plain words a parent would use ("white dresser by the crib").
- `sam_concept`: a short noun phrase that picks out this piece alone for an image segmentation model
  ("white dresser", "tall bookcase").
- `on_it`: each thing standing on it, with its `name`, a `sam_concept` that picks out that thing alone
  ("small potted plant", "wicker basket", "flat stack of books"), and `where`: `top` on the piece's top,
  `shelf` on one of its open shelves.
- `family`: what it is in everyday words ("chest of drawers", "kitchen range", "floor mirror").
- `engine`: `case` when it is a box whose front is drawers, doors and/or open shelves (most
  furniture, ranges, filing cabinets, tool chests); `judge` for anything else.
- `references`: the reference files the next step should read for this piece (see References).
  Always include the one for its family, plus `weights` when things stand on it.

Also name the room (`room`) and say who the photo suggests lives or plays there (`people`), such as
"toddler: crib and toys" or "older adult: walking frame by the bed". Then guess it in two fields the
page shows as chips the person confirms: `child` is `crawling` (a baby not walking yet: a crib, a
play mat, baby gear), `climbing` (a toddler, 1-3: a toddler bed, push toys, a high chair),
`older_kids` (school-age toys, a bunk bed) or `none`; `older` is `lives_here` (a walking frame, grab
bars, a lift chair) or `no`. Use `unknown` whenever the photo doesn't show it; never guess from the
style of the room alone.

## Describe

Describe one piece as a case for the engine: a box on a plinth or legs, whose front is a stack of
zones from the floor up. Each zone is one of:
- `drawers`: `rows` x `cols` drawers;
- `doors`: `cols` door leaves side by side, hinged at the `side` (wardrobes, cabinets) or at the
  `bottom` (an oven door, a drop-front desk), with `shelves` boards behind them;
- `open`: open shelving with `shelves` boards inside (not counting the top and bottom) and `cols`
  compartments across.

Each zone takes a `share` of the inside height, and the shares are scaled to fill it. Each zone also
says what is kept in it (`contents`, a key of the contents catalog, or `none`) and how full it is
(`fill`, 0 to 1). Drawers of clothes are `clothes` at 1.0, the test standard's full drawer. Examples:
a dresser is one drawers zone; a wardrobe is a drawers zone under a doors zone; a bookcase is one open zone;
a range is a drawer, then a bottom-hinged door, then a short open band for the cooktop.

Steps:
1. Pick the closest worked example (`example`). Its numbers are the defaults; change only what the
   photo shows.
2. Measure width and height in cm against things of known size: doors ~203 cm tall, outlet plates
   ~11.4 cm, light switches ~120 cm above the floor, cribs 132-138 cm long, kitchen counters 91 cm
   high, standard bricks or tiles. Say what you leaned on in `size_basis`.
3. Depth rarely shows. Give your best guess from the family's typical depth and set `depth_is_guess`.
4. Count the drawers, doors and shelves you can see. Set the contents and fill from what is visible:
   books on the shelves, dishes behind glass, tools.
5. `material` is a key of the materials catalog. `known_mass_kg` is the empty weight only when you
   recognize the product or the family has a typical weight in the references; otherwise leave it null.
6. `drawer_runners`: `metal_slides` (most modern furniture, all steel cabinets), `wood_runners`
   (older solid-wood pieces), or `unknown`.
7. For each thing on it (`on_it`), in the order given, give: a one- or two-word `short_name`; `shape`
   (`screen` for a flat-panel TV or monitor on a foot, `block` for anything else); its main material;
   whether it is `hard` (would it hurt if it fell on a child's head?); whether it is `breakable`
   (breaks into sharp pieces); whether it is `tempting` (something a small child would climb to get: a
   toy, the remote, a tablet, sweets); `kg` with its contents; `depth_cm`; and `shelf_from_top`: 0 when
   it stands on the top, else which open shelf it stands on, counting down from the highest (1 is the
   highest shelf surface inside the piece). The `weights` reference has typical values.
8. `nearby`: what sleeps, sits or plays in front of it, in two or three plain words ("crib",
   "toddler bed", "sofa"), or null.
9. `anchor_fix`: how this kind of piece is held against tipping, as a short imperative: "Strap it to
   the wall" for furniture, "Fit the anti-tip bracket" for a range, "Bolt it to the floor" for a safe.
   `anchor`: the matching key of the fixes catalog: `strap` (furniture: straps into a wall stud),
   `bracket` (a range's anti-tip bracket) or `tv_strap` (a TV standing on its own).

## Judge

The engine can't build this piece, so judge it from the references. Be conservative: a piece that
could plausibly fall on someone is `maybe` at least.

For each risk (child, adult, quake) give a `status` (`tips`, `maybe` or `holds`) and one short
sentence (`says`) on what happens, in plain words, with no numbers. A risk that doesn't apply holds.
Give one to three `fixes`, the most effective first. Each fix has a short title, a one-sentence
`why`, an `icon`, and `after`, the three statuses once it is done. Icons: `strap` (tie or clip it to
the wall), `lock` (latch it shut), `top` (take things off it or move it lower), `distance` (keep people
out of where it would land), `tv` (strap a TV), `toy` (nothing tempting on it), `weight` (heavy things
low), `hand` (keep everyday things within reach), `latch` (latch doors against shaking), `search`
(check for a recall). If one fact would settle the verdict (is it anchored? which floor?), ask it as a
`question` with two to four options, each with its `after` statuses. Otherwise set the question to null.
`basis` names the guidance you relied on.

## Match

You get a new photo of a room, then photos of rooms already checked in this home, each with its id. Say
which earlier room the new photo shows (`room`), or `none`.

It is the same room when the space itself is the same: the walls, windows, doors, floor and anything
built in line up, even from another angle, in other light, or with furniture moved, added or taken away.
Furniture alone doesn't make it the same room: the same white dresser in another bedroom is another
room. When you can't tell, answer `none`, because a wrong match carries one room's answers into another.

Write `why` first, in at most 20 words: the fixed features that match or differ. Then `room`.

## References

Read only the ones the piece needs:
- `rooms`: what tips in each kind of room, and who is at risk there.
- `case-furniture`: dressers, chests, wardrobes, bookcases, shelving, cabinets, hutches, media
  units, filing cabinets, tool chests, shoe cabinets: typical sizes, weights, fronts, and how to
  describe them as zones.
- `appliances-and-screens`: TVs, ranges and ovens, stacked washers and dryers, microwave carts,
  refrigerators.
- `other-hazards`: mirrors, floor lamps, coat racks, safes, tall decor, wall-mounted shelves and TVs.
- `weights`: what things weigh: contents, TVs by size, things people put on top.
- `standards`: the tests behind the engine's verdicts and where their numbers come from.
