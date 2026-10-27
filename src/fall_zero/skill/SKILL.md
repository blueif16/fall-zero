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
anything already fixed to the wall. A TV, lamp or box standing on a piece goes in that piece's
`on_top`, never as a piece of its own. Each item on top gets its own entry, and a stack of boxes is one entry.

For each piece:
- `name`: a few plain words a parent would use ("white dresser by the crib").
- `sam_concept`: a short noun phrase that picks out this piece alone for an image segmentation model
  ("white dresser", "tall bookcase"). Do the same for each item on top.
- `family`: what it is in everyday words ("chest of drawers", "kitchen range", "floor mirror").
- `engine`: `case` when it is a box whose front is drawers, doors and/or open shelves (most
  furniture, ranges, filing cabinets, tool chests); `judge` for anything else.
- `references`: the reference files the next step should read for this piece (see References).
  Always include the one for its family, plus `weights` when things stand on it.

Also name the room (`room`) and say who the photo suggests lives or plays there (`people`), such as
"toddler: crib and toys" or "older adult: walking frame by the bed".

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
7. For each item on top, in the order given, give: a one- or two-word `short_name`; `shape`
   (`screen` for a flat-panel TV or monitor on a foot, `block` for anything else); its main material;
   whether it is `hard` (would it hurt if it fell on a child's head?); whether it is `breakable`
   (breaks into sharp pieces); `kg` with its contents; and `depth_cm`. The `weights` reference has
   typical values.
8. `nearby`: what sleeps, sits or plays in front of it, in two or three plain words ("crib",
   "toddler bed", "sofa"), or null.
9. `anchor_fix`: how this kind of piece is held against tipping, as a short imperative: "Strap it to
   the wall" for furniture, "Fit the anti-tip bracket" for a range, "Bolt it to the floor" for a safe.
   `anchor_how`: one sentence on what that takes, such as "An anti-tip strap screwed into a stud.
   About $15, 10 minutes."

## Judge

The engine can't build this piece, so judge it from the references. Be conservative: a piece that
could plausibly fall on someone is `maybe` at least.

For each risk (child, adult, quake) give a `status` (`tips`, `maybe` or `holds`) and one short
sentence (`says`) on what happens, in plain words, with no numbers. A risk that doesn't apply holds.
Give one to three `fixes`, the most effective first. Each fix has a short title, a one-sentence
`why`, an `icon` (`strap`, `lock`, `top`, `distance` or `move`), and `after`, the three statuses
once it is done. If one fact would settle the verdict (is it anchored? which floor?), ask it as a
`question` with two to four options, each with its `after` statuses. Otherwise set the question to null.
`basis` names the guidance you relied on.

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
