"""Time actual end-to-end answers and record the model's actual device."""
import os
import json
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "How does resource-specific consent limit an app's permissions?"
with httpx.Client(base_url="http://127.0.0.1:8765", timeout=180) as client:
    client.post("/api/login", json={"username":"atharv","password":os.environ["QUFO_PASSWORD"]}).raise_for_status()
    runs=[]
    already_loaded=client.get("/api/workspace").json()["ai"].get("model_device") is not None
    labels=["warm"]*3 if already_loaded else ["cold","warm","warm"]
    for label in labels:
        client.post("/api/chat/reset").raise_for_status()
        started=time.perf_counter()
        response=client.post("/api/chat",json={"question":QUESTION})
        response.raise_for_status()
        elapsed=round(time.perf_counter()-started,3)
        answer=response.json()
        runtime=client.get("/api/workspace").json()["ai"]
        assert runtime["model_device"]=="cuda:0",runtime
        assert answer["mode"].startswith("AI synthesis"),answer["mode"]
        assert answer["citations"]
        runs.append({"kind":label,"seconds":elapsed,"mode":answer["mode"],"runtime":runtime,"answer":answer["answer"]})
        print(json.dumps({"kind":label,"seconds":elapsed,"runtime":runtime},ensure_ascii=True),flush=True)
    started=time.perf_counter()
    response=client.post("/api/chat",json={"question":"How does resource-specific consent scope permissions to an individual team or chat?"})
    response.raise_for_status()
    runtime=client.get("/api/workspace").json()["ai"]
    assert runtime["embedding_device"]=="cuda:0",runtime
    print(json.dumps({"kind":"uncached embedding query","seconds":round(time.perf_counter()-started,3),
                      "runtime":runtime},ensure_ascii=True),flush=True)
    baseline_path=ROOT/"docs/gpu-performance.json"
    baseline=json.loads(baseline_path.read_text(encoding="utf-8")).get("previous_cpu_observation_seconds") if baseline_path.exists() else None
    result={"question":QUESTION,"previous_cpu_observation_seconds":baseline,"runs":runs,"verified_embedding_runtime":runtime,
            "note":"One laptop, same model and question. Cold includes lazy model load; warm reuses resident model weights."}
    (ROOT/"data/gpu-benchmark.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
