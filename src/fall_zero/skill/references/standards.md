# The tests behind the verdicts

The engine runs the same three child tests on every piece it builds, plus an adult grab and simulated
earthquakes. Where a piece falls outside a standard's scope, the test is borrowed and the card says so.

## Clothing storage: ASTM F2057-23, mandatory in the US as 16 CFR 1261 (the STURDY Act)
- Scope: free-standing units with drawers and/or hinged doors for clothing, at least 27 in tall, at
  least 30 lb, and at least 3.2 ft³ of enclosed storage: dressers, chests, wardrobes, armoires,
  door chests. Bookcases and entertainment furniture are out of scope.
- Every drawer and door is opened unless an interlock holds it shut. An interlock must keep its
  drawer closed under 30 lb for 5 s.
- Clothing load: when more than half the storage pulls out, drawers are filled at 8.5 lb/ft³, held
  30 s; it must not tip.
- Horizontal force: 10 lbf outward at the highest handhold, no higher than 56 in, for 10 s.
- Carpet and child: a 0.43 in block under the rear, and a 60 lb weight hung on the door or drawer
  most likely to tip it, for 30 s.

## TV stands and carts: UL 1678
- Carts, stands and entertainment centers for audio and video equipment. It includes a 50 lb load on
  a door, drawer, shelf or other part within 30 in of the floor, which must not tip the stand.

## Office storage: ANSI/BIFMA X5.9-2019
- Office storage units (filing cabinets, storage cabinets): stability with one or more drawers
  extended and loaded, a vertical force on an extended drawer or open door, and a horizontal force.

## Ranges: UL 858 (electric) and ANSI Z21.1 (gas)
- Since 1991: a range must stay up with 250 lb on its open oven door, which in practice means the
  anti-tip bracket is installed.

## Tip restraints (wall straps): ASTM F3096
- A tip restraint must hold a 50 lbf static load. The engine checks that a strap is never asked for
  more.

## Europe and international
- EN 14749 (domestic and kitchen storage) and ISO 7171 (storage unit test methods) follow the same
  pattern: drawers to their stop, doors at 90 degrees, a vertical force on the front edge of an open
  drawer or door, and a horizontal force.

## Not covered by any standard (the engine's assumptions)
- Adult grab: 100-300 N pulled at 0.95 m.
- Earthquakes: synthetic ground motion in four stages, at 0.15, 0.30, 0.50 and 0.80 g peak floor
  acceleration (USGS ShakeMap intensities VI-IX). An upper floor sways with the building at 1.5 Hz.
  Shut drawers slide out on their runners; doors stay shut.
- Contents densities marked "assumption" in the contents catalog.
