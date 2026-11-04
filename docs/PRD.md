# Fall-Zero — Product Requirements

*v0.1 · Oct 26, 2026 · Meta Global AI Developer Hackathon (10-day build)*

*The flow as built (2026-11-04), from who's home to keeping it safe, is [FLOW.md](FLOW.md); why, [JOURNEY.md](JOURNEY.md).*

> **View in Room tells you if it fits. Fall-Zero tells you if it falls.**

## 1. Problem

Furniture and TV tip-overs send about 22,500 Americans to the emergency room every year. Since 2000 they have killed 581 people, 472 of them children. About a third of parents of young children have never anchored their furniture. ER visits among adults over 60 are rising too. In the 1994 Northridge earthquake, 55% of injuries came from falling furniture and objects; only 1% came from building damage.

The federal stability standard (ASTM F2057-23, under the STURDY Act) has only applied to clothing storage units made after Sept 1, 2023. It doesn't cover bookcases or TV stands at all. So most furniture already in homes, and most of what is sold secondhand, has never been tested. Some of it has been recalled outright: IKEA recalled 29 million dressers in 2016, and millions are still in use. Recalled products also keep getting resold on Facebook Marketplace.

Families can't tell which of their pieces are the dangerous ones. Anchoring kits cost under $20 and take under 20 minutes to install, so knowing *which* pieces to anchor is the whole problem.

## 2. Users

- **Primary:** parents of children under 6.
- **Secondary:** adult children setting up a home for an elderly parent, households in earthquake zones, and people buying furniture secondhand.

## 3. Goals and non-goals

**Goals**

1. Go from a phone video or a Marketplace listing to a per-piece tip-over verdict in under 3 minutes.
2. Simulate the three scenarios that injure people: a child climbing, an elderly person grabbing furniture for support, and earthquake shaking.
3. Give a ranked list of fixes: which pieces to anchor, which heavy items to move lower, and how far to keep each piece from the bed or crib.
4. Prove the physics against real measurements, not LLM judgment.

**Non-goals:** fire, structural engineering, safety certification, a native AR app, and furniture e-commerce.

## 4. Core flow

1. **Entry.** The user asks in Muse ("Is this dresser safe for my 2-year-old?") through the Fall-Zero connector, or opens the web app directly.
2. **Capture.** A 30-second phone video of the room, saved once as the household profile. The profile records the room layout, floor type (carpet vs hard floor), where beds and cribs are, and who lives there.
3. **Optional listing.** A Marketplace listing photo plus the dimensions given in the listing.
4. **Reconstruct.** Each piece of furniture is segmented and rebuilt as a 3D model, then given real-world scale from reference objects (doors, outlet plates) or the listed dimensions.
5. **Identify.** The product model is recognized, and its factory weight and recall status are looked up.
6. **Simulate.** Three scenarios run side by side on a physics model of each piece.
7. **Verdict.** For each piece: pass, fail, or a range, with the reason; a ranked fix list; and a recall flag where one applies.

## 5. Requirements

| Priority | Requirement | Notes |
| --- | --- | --- |
| P0 | Segment every piece of furniture and the objects on it from the room video | SAM 3.1 |
| P0 | 3D reconstruction with real-world scale | SAM 3D Objects; scale from reference objects or listed dimensions |
| P0 | Estimate mass and centre of gravity, with a clothing-load assumption | Muse Spark identifies the model and searches its spec weight; otherwise a range |
| P0 | **Child scenario:** run the three ASTM F2057-23 tests virtually | Clothing load with all drawers open; 10 lb horizontal at ≤56 in; 60 lb on an open drawer with a 0.43 in carpet block |
| P0 | **Elderly scenario:** horizontal grab force at hand height | No standard exists, so it is labelled as a model assumption |
| P0 | **Earthquake scenario:** rigid-body rocking and overturning under a recorded ground motion | Physics engine (MuJoCo) |
| P0 | Ranked fix list and tip-direction relative to beds and cribs |  |
| P0 | Honesty flags: "cannot determine" for anchoring hidden behind the piece, unknown drawer contents, or missing scale | Results shown as ranges, never false precision |
| P1 | Marketplace listing input: a single photo plus listed dimensions | SAM 3D single-image reconstruction |
| P1 | Recall check against CPSC recall data | Model name match |
| P1 | Muse connector (MCP) | Thin entry point; built last |

## 6. Validation (the proof)

- **Pull test.** On 8 or more real pieces of furniture, pull horizontally at the top with a luggage scale until the piece *just begins* to lift, then compare that force with Fall-Zero's prediction. **Target: median error ≤20%.** Use empty pieces, with a spotter, and never let a piece actually tip.
- **Known-model sanity check.** Recalled MALM-type dressers must fail when unanchored, and post-2023 compliant models must pass the child tests.
- **Coverage.** Report the share of pieces that get a definite verdict versus a range or "cannot determine".

## 7. Demo (about 90 seconds)

1. **Before.** "We want to buy a used dresser on Marketplace for our toddler's room."
2. **One action.** Paste the listing; the toddler's room is already scanned.
3. **The visible moment.** The dresser appears in the room and the three scenarios play side by side: the child test fails, and in the earthquake it tips toward the crib.
4. **Proof.** Luggage-scale pull tests on real furniture: predicted force vs measured force.
5. **Honesty.** "Unknown brand, no dimensions listed, so here is a range rather than a single number."
6. **Close.** "Anchor it, keep it at least X from the crib, and the cost is $20."

## 8. Models and stack

- **SAM 3.1** for segmentation and **SAM 3D Objects** for reconstruction.
- **Muse Spark** for product identification, spec and recall lookup, and the report.
- **MuJoCo** for the physics.
- A **web app**, plus the **Muse connector** as an entry point.

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| Mass estimate is wrong | Look up the spec weight by product model; calibrate with pull tests; show ranges |
| Monocular video has no real-world scale | Use standard-size reference objects and listed dimensions |
| The earthquake simulation looks authoritative | Label it as illustrative and compare with published shake-table studies |
| Muse may not pass photos or video to connectors | Test on day 1; fallback is a connector that returns a capture link |
| Raising "recalled items on Marketplace" with Meta judges | Frame it as a safety layer for View in Room |
| Users read the output as certification | Always say "screening, not certification" |

## 10. Milestones

| Days | Deliverable |
| --- | --- |
| 1–2 | Pull-test rig and data; virtual F2057 tests on a hand-measured box (the eval harness comes first) |
| 3–4 | Video → segmentation → 3D reconstruction → scale, end to end |
| 5–6 | Mass and model identification; all three scenarios; verdict and fix list |
| 7 | Marketplace listing input and recall check |
| 8 | Muse connector |
| 9–10 | Final pull-test numbers, demo recording, pitch rehearsal |

## 11. Open questions

- Hackathon rules on reusing existing code (to be published by the organizers).
- Whether Muse connectors can receive images.
- Which earthquake record to use for the demo.
- Exact disclaimer wording.

## Sources

- CPSC tip-over injury and death statistics: [https://www.woodworkingnetwork.com/news/woodworking-industry-news/cpsc-despite-progress-tip-overs-still-cause-injury-and-death](https://www.woodworkingnetwork.com/news/woodworking-industry-news/cpsc-despite-progress-tip-overs-still-cause-injury-and-death)
- Share of parents who haven't anchored furniture: [https://www.safetyandhealthmagazine.com/?p=18795](https://www.safetyandhealthmagazine.com/?p=18795)
- Rising ER visits among adults 60+, and the post-2023 scope of the standard: [https://www.cbsnews.com/philadelphia/news/tvs-furniture-tipping-over-children-consumer-product-safety-commision](https://www.cbsnews.com/philadelphia/news/tvs-furniture-tipping-over-children-consumer-product-safety-commision)
- ASTM F2057-23 test details: [https://www.furnituretoday.com/industry-issue/mandatory-furniture-stability-standard-goes-into-effect-sept-1](https://www.furnituretoday.com/industry-issue/mandatory-furniture-stability-standard-goes-into-effect-sept-1)
- Bookcases and TV stands excluded from the standard: [https://www.furnituretoday.com/industry-news/sturdy-act-goes-into-effect-this-week](https://www.furnituretoday.com/industry-news/sturdy-act-goes-into-effect-this-week)
- Northridge earthquake injury causes: [https://cusec.org/earthquake-safety-preparedness/before-an-earthquake/1-secure-your-space](https://cusec.org/earthquake-safety-preparedness/before-an-earthquake/1-secure-your-space)
- IKEA's 29 million dresser recall: [https://www.cbsnews.com/dfw/news/ikea-recalls-29-million-dressers-chests-after-6-kids-killed/](https://www.cbsnews.com/dfw/news/ikea-recalls-29-million-dressers-chests-after-6-kids-killed/)
- Recalled products still sold on Facebook Marketplace: [https://www.foxbusiness.com/lifestyle/recalled-products-tied-infant-deaths-still-being-sold-metas-facebook-marketplace-lawmakers-say](https://www.foxbusiness.com/lifestyle/recalled-products-tied-infant-deaths-still-being-sold-metas-facebook-marketplace-lawmakers-say)
- View in Room, powered by SAM 3D: [https://www.socialmediatoday.com/news/meta-tests-virtual-try-on-for-furniture-on-marketplace/805960/](https://www.socialmediatoday.com/news/meta-tests-virtual-try-on-for-furniture-on-marketplace/805960/)