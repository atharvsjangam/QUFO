"""Check that research-note URLs point to available official articles."""
import json
from pathlib import Path
import httpx
sources=json.loads((Path(__file__).resolve().parents[1]/"sources/teams.json").read_text(encoding="utf-8"))
for source in sources:
    response=httpx.get(source["url"],follow_redirects=True,timeout=30)
    print(response.status_code,source["title"],len(response.content),flush=True)
    response.raise_for_status()
