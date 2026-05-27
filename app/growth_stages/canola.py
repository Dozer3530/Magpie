"""BBCH growth stages for canola (Brassica napus).

Each entry is (code, description). The code matches the standard BBCH scale.
Edit this list to match the conventions your surveyors actually use; the
GUI growth-stage picker reads it directly.
"""
from __future__ import annotations

STAGES: list[tuple[str, str]] = [
    # 0 - Germination
    ("00", "Dry seed"),
    ("01", "Beginning of seed imbibition"),
    ("03", "Seed imbibition complete"),
    ("05", "Radicle emerged from seed"),
    ("07", "Hypocotyl with cotyledons breaking through seed coat"),
    ("09", "Emergence: cotyledons break through soil surface"),

    # 1 - Leaf development
    ("10", "Cotyledons completely unfolded"),
    ("11", "First true leaf unfolded"),
    ("12", "2 true leaves unfolded"),
    ("13", "3 true leaves unfolded"),
    ("14", "4 true leaves unfolded"),
    ("15", "5 true leaves unfolded"),
    ("16", "6 true leaves unfolded"),
    ("17", "7 true leaves unfolded"),
    ("18", "8 true leaves unfolded"),
    ("19", "9 or more true leaves unfolded"),

    # 2 - Formation of side shoots
    ("20", "No side shoots"),
    ("21", "Beginning of side shoot development"),
    ("22", "2 side shoots detectable"),
    ("23", "3 side shoots detectable"),
    ("25", "5 side shoots detectable"),
    ("29", "End of side shoot development"),

    # 3 - Stem elongation
    ("30", "Beginning of stem elongation"),
    ("31", "1 visibly extended internode"),
    ("32", "2 visibly extended internodes"),
    ("33", "3 visibly extended internodes"),
    ("35", "5 visibly extended internodes"),
    ("39", "9 or more visibly extended internodes"),

    # 5 - Inflorescence emergence
    ("50", "Flower buds present, still enclosed by leaves"),
    ("51", "Flower buds visible from above ('green bud')"),
    ("52", "Flower buds free, level with the youngest leaves"),
    ("53", "Flower buds raised above the youngest leaves"),
    ("55", "Individual flower buds visible (still closed)"),
    ("57", "Individual flower buds yellow ('yellow bud')"),
    ("59", "First petals visible, flower buds still closed"),

    # 6 - Flowering
    ("60", "First flowers open"),
    ("61", "10% of flowers on main raceme open"),
    ("62", "20% of flowers on main raceme open"),
    ("63", "30% of flowers on main raceme open"),
    ("64", "40% of flowers on main raceme open"),
    ("65", "Full flowering: 50% open, first petals fallen"),
    ("67", "Flowering declining"),
    ("69", "End of flowering"),

    # 7 - Development of fruit
    ("71", "10% of pods reached final size"),
    ("72", "20% of pods reached final size"),
    ("73", "30% of pods reached final size"),
    ("74", "40% of pods reached final size"),
    ("75", "50% of pods reached final size"),
    ("76", "60% of pods reached final size"),
    ("77", "70% of pods reached final size"),
    ("78", "80% of pods reached final size"),
    ("79", "Nearly all pods reached final size"),

    # 8 - Ripening
    ("80", "Beginning of ripening: seed green, filling pod cavity"),
    ("81", "10% of pods ripe, seeds dark and hard"),
    ("83", "30% of pods ripe"),
    ("85", "50% of pods ripe"),
    ("87", "70% of pods ripe"),
    ("89", "Fully ripe: nearly all pods ripe, seeds dark and hard"),

    # 9 - Senescence
    ("97", "Plant dead and dry"),
    ("99", "Harvested product"),
]
