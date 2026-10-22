"""Download official CUDA wheels in verified, resumable ranges."""
import concurrent.futures
import hashlib
import html
import json
import re
import sys
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/"data"/"wheels"
DEST.mkdir(parents=True,exist_ok=True)


def download(package, version):
    abi=f"cp{sys.version_info.major}{sys.version_info.minor}"
    name=f"{package}-{version}+cu128-{abi}-{abi}-win_amd64.whl"
    encoded=name.replace("+","%2B")
    with httpx.Client(timeout=90,follow_redirects=True,limits=httpx.Limits(max_connections=6)) as client:
        listing=client.get(f"https://download.pytorch.org/whl/cu128/{package}/")
        listing.raise_for_status()
        match=re.search(r'href="([^"]*'+re.escape(encoded)+r')#sha256=([a-f0-9]{64})"',listing.text)
        if not match:raise RuntimeError("No official wheel/checksum found for "+name)
        expected=match.group(2)
        url="https://download.pytorch.org/whl/cu128/"+encoded
        head=client.get(url,headers={"Range":"bytes=0-0"})
        head.raise_for_status()
        if head.status_code!=206:raise RuntimeError("Official download endpoint did not honor byte ranges.")
        size=int(head.headers["content-range"].split("/")[-1])
        path=DEST/name
        progress=DEST/(name+".json")
        state=json.loads(progress.read_text()) if progress.exists() else {}
        done=set(state.get("done",[])) if state.get("sha256")==expected and path.exists() else set()
        if not done:
            with path.open("wb") as output:output.truncate(size)
        step=16*1024*1024
        offsets=list(range(0,size,step))
        def part(offset):
            end=min(offset+step,size)-1
            for attempt in range(3):
                try:
                    response=client.get(url,headers={"Range":f"bytes={offset}-{end}"})
                    response.raise_for_status()
                    if response.status_code!=206 or len(response.content)!=end-offset+1 or response.headers.get("content-range")!=f"bytes {offset}-{end}/{size}":
                        raise RuntimeError("Unexpected byte range; refusing to install an unverified download.")
                    with path.open("r+b") as output:
                        output.seek(offset);output.write(response.content)
                    return offset
                except Exception:
                    if attempt==2:raise
        print(f"Downloading {name}: {size/1e9:.2f} GB; {len(done)} ranges already present",flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(part,offset):offset for offset in offsets if offset not in done}
            for future in concurrent.futures.as_completed(futures):
                done.add(future.result())
                progress.write_text(json.dumps({"sha256":expected,"done":sorted(done)}))
                if len(done)%16==0 or len(done)==len(offsets):
                    print(f"{package}: {len(done)}/{len(offsets)} ranges ({100*len(done)/len(offsets):.0f}%)",flush=True)
        digest=hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda:source.read(8*1024*1024),b""):digest.update(chunk)
        if digest.hexdigest()!=expected:
            progress.unlink(missing_ok=True)
            raise RuntimeError("Official SHA-256 did not match for "+name)
        print("Official SHA-256 verified:",name,flush=True)
        return path


if __name__=="__main__":
    import subprocess
    wheels=[download("torch","2.8.0"),download("torchvision","0.23.0")]
    subprocess.run([sys.executable,"-m","pip","install","--no-cache-dir",*[str(p) for p in wheels]],check=True)
    for path in wheels:
        path.unlink()
        Path(str(path)+".json").unlink(missing_ok=True)
    print("CUDA-enabled PyTorch is installed in QUFO.",flush=True)
