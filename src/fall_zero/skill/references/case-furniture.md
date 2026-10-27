# Case furniture

Anything that is a box with drawers, doors or open shelves on its front. The engine builds all of
these from zones (see Describe). The worked examples in the examples catalog cover the common ones.
Pick the closest and change what the photo shows.

## Dressers and chests (clothing storage)
- Wide low dressers: 120-160 cm wide, 45-50 cm deep, 75-90 cm tall, 2-3 columns of drawers (IKEA MALM
  6-drawer: 160 x 48 x 78 cm). Tall chests: 75-100 cm wide, 45-50 cm deep, 110-130 cm tall, 4-6 rows.
  Kids' dressers and changing-table bases: 70-90 cm wide, 40-45 cm deep, about 70 cm tall.
- Mostly particleboard or MDF on metal slides; older or pricier pieces are solid wood, sometimes on
  wood runners. Mid-century pieces stand on legs.
- In 2016 IKEA recalled about 29 million MALM and other chests and dressers after child deaths.
  Since September 2023 US law (the STURDY Act, 16 CFR 1261) requires new clothing storage units
  to pass the ASTM F2057-23 tests.
- Zones: one drawers zone; contents `clothes`, fill 1.

## Wardrobes and armoires
- 50-200 cm wide, 55-60 cm deep, 180-236 cm tall. Doors over a hanging rail, sometimes drawers below.
  Covered by the same clothing-storage rule.
- An open door is a long lever: a child hanging on its edge pulls with the door's full width in front.
- Zones: drawers (if any) under a doors zone with `cols` = door leaves; contents `hanging_clothes`.

## Bookcases and open shelving
- Tall narrow bookcases: 40-80 cm wide, 28-30 cm deep, 180-240 cm tall (IKEA BILLY: 80 x 28 x 202 cm).
  The shallow depth is why they tip. They are lightest and most dangerous when empty or loaded only
  at the top.
- Cube shelves: 77 x 39 cm per 2-column unit, 77-147 cm tall (IKEA KALLAX 2x4: 77 x 39 x 147 cm).
- Steel shelving (garage, pantry): 90-120 cm wide, 45-60 cm deep, 150-180 cm tall, often 15-25 kg
  empty, loaded with heavy things high up.
- Not clothing storage: no mandatory US test. The engine borrows the child tests.
- Zones: one open zone; `shelves` = boards between top and bottom; `cols` = compartments across;
  contents `books`, `toys`, `pantry` or `tools`; fill from the photo.

## Media units and TV stands
- Low and wide: 100-200 cm wide, 35-45 cm deep, 40-60 cm tall. The stand rarely tips by itself. The
  hazard is the TV on it, and a child climbing the open doors or drawers to reach it.
- The TV-stand standard (UL 1678) loads a door, drawer or shelf within 30 in of the floor with 50 lb.
- Zones: open shelves, doors or drawers as seen; contents `media`.

## Hutches, china cabinets and display cabinets
- Hutches: a base of doors and drawers (about half the height) under a top of open shelves or glass
  doors, 90-150 cm wide, 40-50 cm deep, 180-210 cm tall. Heavy, often solid wood, top-loaded with
  dishes.
- Display or curio cabinets: glass doors and glass shelves, 40-90 cm wide, 35-45 cm deep, 160-200
  cm tall. Glass makes any fall worse (`breakable`).
- Zones: as seen, from the floor up; contents `dishes`.

## Filing cabinets and office storage
- Vertical steel files: 38-46 cm wide, 63-71 cm deep, 2-5 drawers (4-drawer: about 132 cm tall,
  35-45 kg empty). A full drawer of paper weighs 20-30 kg, so two loaded drawers pulled out can tip
  the cabinet. Office-grade units have interlocks that let one drawer open at a time.
- Lateral files: 76-107 cm wide, 46-50 cm deep, wide drawers.
- Office storage is tested to ANSI/BIFMA X5.9, not the clothing-storage rule.
- Zones: drawers; contents `files`; material `steel`; give `known_mass_kg`.

## Tool chests and garage cabinets
- Rolling tool cabinets: 60-140 cm wide, 45-60 cm deep, 90-110 cm tall, often with a top chest
  stacked on them, many shallow drawers full of steel tools, on casters (base `legs`, low).
- Zones: drawers; contents `tools`; material `steel`; give `known_mass_kg` (about 40-120 kg empty).

## Shoe cabinets and linen towers
- Tilt-out shoe cabinets are only 17-30 cm deep and 100-150 cm tall: they tip from a light pull at
  the top. Linen towers: 30-40 cm wide and deep, 150-180 cm tall.
- Zones: doors or open shelves; contents `linens` or none.

## Describing the front as zones
- Count from the floor up. Shares are relative: a wardrobe with drawers in the bottom quarter is
  `[drawers share 0.25, doors share 0.75]`.
- Doors with shelves behind: `doors` with `shelves`. Glass doors are still doors.
- Side-by-side sections of different kinds (doors left, drawers right) can't be represented
  exactly: use the kind that covers most of the front, and say so in `size_basis`.
- Legs or casters: base `legs` with their height. Solid plinth or sides to the floor: base `plinth`.
