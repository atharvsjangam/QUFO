"""Measure retrieval against a small, explicit Microsoft Teams question set."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

CASES = [
 ("What replaced Electron in the new Teams architecture?", "Architecture"),
 ("Which framework replaced AngularJS?", "Architecture"),
 ("How is GraphQL used in the client data layer?", "Architecture"),
 ("What connects the application components through IPC?", "Architecture"),
 ("Why separate data handling from rendering?", "Architecture"),
 ("What does Fluent UI v9 contribute?", "Architecture"),
 ("What were the performance goals for the preview?", "Performance"),
 ("How much memory did the new design aim to use?", "Performance"),
 ("What launch and meeting join problems were targeted?", "Performance"),
 ("How did Microsoft Intune help deployment and updates?", "Performance"),
 ("Were the performance statements measured by QUFO?", "Performance"),
 ("How does WebView2 receive independent runtime updates?", "Security"),
 ("How did the native host change security considerations?", "Security"),
 ("Does the security architecture prove there are no vulnerabilities?", "Security"),
 ("When did Windows and Mac reach general availability?", "Milestone"),
 ("Were government cloud and VDI generally available on October 5?", "Milestone"),
 ("How did update channels affect the rollout schedule?", "Milestone"),
 ("How does tab single sign-on use Microsoft Entra ID tokens?", "Authentication"),
 ("What is resource-specific consent and how are permissions scoped?", "Permissions"),
 ("What are the prerequisites for hosting a tab in an iframe?", "Known limitations"),
 ("What is Live Share and how is collaboration synchronized?", "Meetings"),
 ("Which fields define the Teams app manifest?", "App manifest"),
 ("What causes Teams Store validation failures?", "Known limitations"),
 ("How does an incoming webhook send data to a Teams channel?", "Integration"),
 ("What permissions are required to access browser devices?", "Permissions"),
 ("What is the recipe for chocolate tiramisu?", None),
 ("How many moons orbit Neptune?", None),
 ("What caused the volcanic eruption at Vesuvius?", None),
]
user={"id":"atharv","role":"admin","team":"Research"}
with server.db() as c:
 categories={r["id"]:r["category"] for r in c.execute("SELECT id,category FROM docs")}
results=[]
for question, expected in CASES:
 evidence,mode=server.retrieve(question,user)
 found=[categories.get(e["document_id"]) for e in evidence[:3]]
 passed=expected in found if expected else not evidence
 results.append({"question":question,"expected":expected,"retrieved_categories":found,"passed":passed})
out=Path(__file__).resolve().parents[1]/"docs"/"retrieval-results.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({"passed":sum(r["passed"] for r in results),"total":len(results),
                          "metric":"Expected source category appears in top 3; unrelated questions abstain.",
                          "note":"Curated smoke evaluation, not a general benchmark or an answer-accuracy score.",
                          "results":results},indent=2),encoding="utf-8")
print(f"Retrieval checks: {sum(r['passed'] for r in results)}/{len(results)}")
for r in results:
 if not r["passed"]:print("Needs attention:",r["question"],r["retrieved_categories"])
