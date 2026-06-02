"""Publish a shareable, self-refreshing progress page.

Writes a single self-contained `magpie-progress.html` into a folder the user
picks — point it at a Google Drive / OneDrive / network synced folder and
coworkers can open the synced *local* copy to watch progress. The page carries
its data inlined (no separate file → works from `file://` with no fetch/CORS
issue) and auto-refreshes every 60s, so an open tab stays current as new copies
sync in. It shows only completeness counts (Field/Lab/Pest per week, per crop)
— no coordinates — so it's safe to share.

"Live" here means: the open page refreshes itself and reflects the last
publish. Magpie re-publishes on each export and via a manual button; an
"Updated <time>" stamp keeps staleness honest when Magpie isn't running.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app import app_settings
from app.services.weeks import all_weeks_progress

PUBLISH_FILENAME = "magpie-progress.html"
_PUBLISH_DIR_KEY = "publish_dir"


def get_publish_dir() -> str | None:
    return app_settings.get(_PUBLISH_DIR_KEY) or None


def set_publish_dir(path: str | Path) -> None:
    app_settings.set_(_PUBLISH_DIR_KEY, str(path))


def build_progress_html() -> str:
    """Render the self-contained progress page from all_weeks_progress()."""
    weeks = sorted(
        all_weeks_progress(),
        key=lambda w: (w.get("created_at") or "", w["iso_week"]),
        reverse=True,  # newest first
    )
    payload = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "weeks": weeks}
    return _TEMPLATE.replace("__DATA__", json.dumps(payload))


def publish_progress(dest_dir: str | Path | None = None) -> Path:
    """Write magpie-progress.html into dest_dir (or the saved publish folder).

    Raises ValueError if no folder is given and none is configured.
    """
    chosen = dest_dir or get_publish_dir()
    if not chosen:
        raise ValueError("No publish folder set — choose a folder first.")
    target = Path(chosen)
    target.mkdir(parents=True, exist_ok=True)
    out = target / PUBLISH_FILENAME
    out.write_text(build_progress_html(), encoding="utf-8")
    return out


_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="60">
<title>Magpie - Weekly progress</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@700;900&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root{--bg:#0B0B0B;--panel:#161616;--ink:#F4F1E8;--ink-soft:#B4B0A4;--ink-faint:#76736A;--line:#F4F1E8;--lime:#C6F000;--blue:#3D6BFF;--amber:#F2A900;--bd:3px}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--ink);font-family:"Archivo",system-ui,sans-serif;padding:28px;min-height:100vh;
    background-image:linear-gradient(rgba(244,241,232,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(244,241,232,.025) 1px,transparent 1px);background-size:40px 40px}
  .wm{font-weight:900;font-size:42px;letter-spacing:-.04em;text-transform:uppercase;line-height:.9}
  .wm .b{color:var(--lime)}
  .sub{font-family:"Space Mono",monospace;font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-soft);margin-top:10px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px;margin-top:26px}
  .card{border:var(--bd) solid var(--line);background:var(--panel);padding:18px;box-shadow:6px 6px 0 var(--lime)}
  .wk{font-weight:900;font-size:24px;text-transform:uppercase;letter-spacing:-.03em}
  .crop{margin-top:14px;padding-top:12px;border-top:2px solid rgba(244,241,232,.18)}
  .crop h4{font-family:"Space Mono",monospace;font-size:11px;font-weight:700;text-transform:uppercase;color:var(--ink-soft);margin-bottom:8px}
  .bar{margin-bottom:9px}
  .lab{display:flex;justify-content:space-between;font-family:"Space Mono",monospace;font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--ink-soft);margin-bottom:4px}
  .lab b{color:var(--ink)}
  .track{height:14px;border:2px solid var(--line);background:#000;overflow:hidden}
  .track i{display:block;height:100%}
  .empty{font-family:"Space Mono",monospace;color:var(--ink-faint);margin-top:26px}
</style></head>
<body>
  <div class="wm">Mag<span class="b">pie</span></div>
  <div class="sub" id="sub"></div>
  <div id="grid" class="grid"></div>
<script>
const PAYLOAD = __DATA__;
const COLORS = {field:"var(--lime)", lab:"var(--blue)", pest:"var(--amber)"};
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];});}
function bar(label, n, total, color){
  const pct = total ? Math.round(n/total*100) : 0;
  return '<div class="bar"><div class="lab"><span>'+label+'</span><b>'+n+'/'+total+'</b></div>'
    + '<div class="track"><i style="width:'+pct+'%;background:'+color+'"></i></div></div>';
}
document.getElementById("sub").textContent = "Weekly progress  -  updated " + PAYLOAD.updated;
const g = document.getElementById("grid");
if(!PAYLOAD.weeks.length){ g.innerHTML = '<div class="empty">No weeks yet.</div>'; }
else g.innerHTML = PAYLOAD.weeks.map(function(w){
  const crops = (w.crops||[]).map(function(c){
    const t = c.total_locations || 9;
    return '<div class="crop"><h4>'+esc(c.display_name)+'</h4>'
      + bar("Field", c.field_locations||0, t, COLORS.field)
      + bar("Lab", c.lab_locations||0, t, COLORS.lab)
      + bar("Pest", c.pest_cards||0, t, COLORS.pest) + '</div>';
  }).join("");
  return '<div class="card"><div class="wk">'+esc(w.iso_week)+'</div>'+crops+'</div>';
}).join("");
</script>
</body></html>
"""
