"""BBCH growth stages for corn / maize (Zea mays).

Each entry is (code, description). Codes follow the standard BBCH scale for
maize; the V/R staging system used in North America is noted in parens where
it maps cleanly. Edit this list to match the conventions your surveyors use.
"""
from __future__ import annotations

STAGES: list[tuple[str, str]] = [
    # 0 - Germination
    ("00", "Dry seed (caryopsis)"),
    ("01", "Beginning of seed imbibition"),
    ("03", "Seed imbibition complete"),
    ("05", "Radicle emerged from caryopsis"),
    ("06", "Radicle elongated, root hairs and/or side roots visible"),
    ("07", "Coleoptile emerged from caryopsis"),
    ("09", "Emergence: coleoptile penetrates soil surface (VE)"),

    # 1 - Leaf development (V stages)
    ("10", "First leaf through coleoptile"),
    ("11", "First leaf unfolded (V1)"),
    ("12", "2 leaves unfolded (V2)"),
    ("13", "3 leaves unfolded (V3)"),
    ("14", "4 leaves unfolded (V4)"),
    ("15", "5 leaves unfolded (V5)"),
    ("16", "6 leaves unfolded (V6)"),
    ("17", "7 leaves unfolded (V7)"),
    ("18", "8 leaves unfolded (V8)"),
    ("19", "9 or more leaves unfolded (V9+)"),

    # 3 - Stem elongation
    ("30", "Beginning of stem elongation"),
    ("31", "1 node detectable"),
    ("32", "2 nodes detectable"),
    ("33", "3 nodes detectable"),
    ("34", "4 nodes detectable"),
    ("35", "5 nodes detectable"),
    ("39", "9 or more nodes detectable"),

    # 5 - Inflorescence emergence (tasseling)
    ("51", "Beginning of tassel emergence"),
    ("53", "Tip of tassel visible"),
    ("55", "Middle of tassel emergence: middle of tassel begins to separate"),
    ("59", "End of tassel emergence: tassel fully emerged and separated (VT)"),

    # 6 - Flowering / silking
    ("61", "Stamens in middle of tassel visible"),
    ("63", "Beginning of pollen shed"),
    ("65", "Upper and lower parts of tassel in flower; silks emerging (R1)"),
    ("67", "Flowering completed; silks drying"),
    ("69", "End of flowering; silks completely dry"),

    # 7 - Development of fruit (kernel fill)
    ("71", "Beginning of grain development: kernels at blister stage, ~16% DM (R2)"),
    ("73", "Early milk"),
    ("75", "Kernels in middle of ear yellowish-white ('milk line'), ~40% DM (R3 milk)"),
    ("79", "Nearly all kernels reached final size"),

    # 8 - Ripening
    ("83", "Early dough: kernel content soft, ~45% DM"),
    ("85", "Dough stage: kernels yellowish, ~55% DM (R4 dough)"),
    ("87", "Physiological maturity: black layer formed, ~60% DM (R5 dent / R6)"),
    ("89", "Fully ripe: kernels hard and shiny, grain moisture below 35%"),

    # 9 - Senescence
    ("97", "Plant dead and dry"),
    ("99", "Harvested product"),
]
