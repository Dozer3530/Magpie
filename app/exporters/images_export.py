"""Copy this week's stored photos into the export folder.

`data/images/<crop>/<week>/<loc>/`  →  `exports/<week>/images/<crop>/<loc>/`

So Excel HYPERLINKs that reference `images/<crop>/<loc>/<filename>` resolve
correctly from inside the deliverable folder (or the unzipped package).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from app import image_storage
from app.db import connect, list_obs_for_week


def copy_week_images(crop_code: str, iso_week: str, week_dir: Path) -> int:
    """Copy all referenced photos for one crop's week into `week_dir/images/...`.

    Returns the number of files copied.
    """
    dest_root = week_dir / "images" / crop_code
    dest_root.mkdir(parents=True, exist_ok=True)

    copied = 0
    with connect() as conn:
        rows = list_obs_for_week(conn, crop_code, iso_week)
    for row in rows:
        loc_id = row["location_id"]
        names = image_storage.parse_list(row["Images"] if "Images" in row.keys() else "")
        if not names:
            continue
        loc_dest = dest_root / loc_id
        loc_dest.mkdir(parents=True, exist_ok=True)
        for name in names:
            src = image_storage.absolute_path(crop_code, iso_week, loc_id, name)
            if not src.is_file():
                # Filename was referenced (e.g. from a Survey123 import where
                # the media folder was missing) but the file isn't in storage.
                # Skip silently; the export will still have the HYPERLINK,
                # it just won't resolve.
                continue
            shutil.copy2(src, loc_dest / name)
            copied += 1
    return copied
