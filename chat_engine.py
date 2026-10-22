"""Contextual answers grounded in recorded chronology, not model guesses."""
import re
from collections import Counter
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
GENERIC=set("""current open unresolved remaining outstanding available become became start started starting begin began beginning development develop research project work working latest last major update updated updates newest recent recently most milestone milestones next upcoming future problem problems challenge challenges blocker blockers issue issues risk risks facing face when what tell explain please about happen happened happening app application software launch launched release released date dates public preview availability generally full it this that they those we our us have has did does was were""".split())
def terms(text):return set(re.findall(r"[a-z0-9]{3,}",text.lower()))
def topic(doc):return re.split(r"\s*[\u00b7|]\s*",doc["title"])[0].strip()
def resolve_scope(question,docs,context_ids=()):
 if not docs:return [],""
 words=terms(question)-ENGLISH_STOP_WORDS-GENERIC
 named=[d for d in docs if words&terms(topic(d))]
 if named:
  groups={topic(d) for d in named}
  return [d for d in docs if topic(d) in groups]," / ".join(sorted(groups))
 if words:
  matches=[d for d in docs if words&terms(d["title"]+" "+d["text"])]
  if matches:return matches,topic(matches[0]) if len({topic(d) for d in matches})==1 else "the selected sources"
  return [],""
 previous=[d for d in docs if d["id"] in context_ids]
 if previous:
  groups={topic(d) for d in previous}
  return [d for d in docs if topic(d) in groups]," / ".join(sorted(groups))
 counts=Counter(topic(d) for d in docs);name,count=counts.most_common(1)[0]
 if len(counts)==1 or count/len(docs)>=.65:return [d for d in docs if topic(d)==name],name
 return [],""
def intent(question):
 q=question.lower()
 if re.search(r"\b(challenges?|problems?|blockers?|risks?|issues?)\b",q) and re.search(r"\b(next|upcoming|current|open|unresolved|facing|future|remaining|outstanding)\b",q):return "challenges"
 if q.strip(" ?.!") in {"challenges","problems","blockers","issues","risks"}:return "challenges"
 if re.search(r"\b(latest|last|newest|most recent)\b",q) and re.search(r"\b(updates?|milestones?|releases?|changes?|news)\b",q):return "latest"
 if re.search(r"\b(when|date|how long)\b",q) and re.search(r"\b(start(?:ed)?|beg(?:an|in)|beginning|commence(?:d)?|kick(?:ed)? off)\b",q):return "start"
 if re.search(r"\b(when|date)\b",q) and re.search(r"\b(launch(?:ed)?|release(?:d)?|available|availability|preview)\b",q):return "launch"
 return None
def citation(doc):
 return {"id":doc["id"]+"-0","document_id":doc["id"],"title":doc["title"],"text":doc["text"],"date":doc["source_date"],"position":1,"url":doc["url"],"type":"document","score":1.0}
def sentences(text):
 return [s.strip().lstrip("- *>") for s in re.split(r"(?<=[.!?])\s+|\n+",text)
         if len(s.strip())>25 and not s.strip().startswith(("#", chr(96)*3, "|", "[!"))]
def result(answer,documents=(),citations=None,mode="Source-grounded answer"):
 return {"answer":answer,"citations":citations if citations is not None else [citation(d) for d in documents],"mode":mode,"retrieval":"topic context + recorded chronology","notice":""}
def answer_intent(question,docs,records,context_ids=()):
 kind=intent(question)
 if not kind:return None
 scoped,name=resolve_scope(question,docs,context_ids)
 if not scoped:
  if kind=="challenges" and records:scoped,name=[],"your workspace"
  else:
   names=sorted({topic(d) for d in docs})
   return result("Which project or collection do you mean? "+("The accessible collections include "+", ".join(names[:6])+"." if names else "There are no accessible source documents yet."),mode="Clarification needed")
 # Documentation revisions are not product release events.
 engineering=[d for d in scoped if d.get("source_kind")!="official_documentation"]
 milestones=[d for d in engineering if re.search(r"\b(announced|public preview|general availability|launched|released)\b",d["text"],re.I)]
 if kind=="start":
  for d in sorted(scoped,key=lambda x:x["source_date"]):
   for sentence in sentences(d["text"]):
    explicit=re.search(r"\b(development|work|project|research)\b.{0,60}\b(started|began|commenced)\b|\b(started|began|commenced)\b.{0,60}\b(development|work|project|research)\b",sentence,re.I)
    if explicit and not re.search(r"\b(not|no|unknown|undisclosed)\b",sentence,re.I) and re.search(r"\b(19|20)\d{2}\b",sentence):
     return result("The source explicitly records the beginning as follows:\n\n"+sentence+" [1]",[d])
  earliest=min(milestones or engineering or scoped,key=lambda x:(x["source_date"],-int("public preview" in x["text"].lower())))
  event=next((s for s in sentences(earliest["text"]) if re.search(r"announced|public preview|launched|released",s,re.I)),None)
  answer=f"The accessible documents do not establish when development of {name} began. A public announcement date is not the same as a development start date.\n\n"
  answer+=(f"The earliest dated public milestone in this collection is recorded in the source dated {earliest['source_date']}: {event} [1]" if event else f"The earliest source in this collection is dated {earliest['source_date']}; that alone does not establish a project start date. [1]")
  return result(answer,[earliest])
 if kind=="latest":
  if milestones:
   newest=max(milestones,key=lambda x:x["source_date"]);excerpt=" ".join(sentences(newest["text"])[:2])
   return result(f"The latest explicitly tracked product milestone in this collection is from {newest['source_date']}:\n\n{excerpt} [1]\n\nThis is the latest milestone in the collected evidence, not a claim about the latest live product release. Documentation revision dates are tracked separately.",[newest])
  newest=max(scoped,key=lambda x:x["source_date"])
  return result(f"The most recently dated source in this collection is {newest['title']} ({newest['source_date']}). [1]\n\nIts documentation update date does not establish the latest major product release. No dated product-release milestone is recorded in this collection.",[newest])
 if kind=="launch":
  target="public preview" if "preview" in question.lower() else "general availability"
  matches=[d for d in milestones if target in d["text"].lower()]
  if matches:
   chosen=min(matches,key=lambda x:x["source_date"]);sentence=next(s for s in sentences(chosen["text"]) if target in s.lower())
   return result(sentence+" [1]\n\nThis records a public release milestone, not when internal development began.",[chosen])
  return result("The accessible sources do not establish that release date. A documentation update date is not a product launch date.",scoped[:1],mode="Evidence gap")
 if kind=="challenges":
  issues=[r for r in records if r["kind"]=="Issue" and r["status"] not in {"Completed","Resolved"}]
  if issues:
   issues.sort(key=lambda r:(r["pinned"],{"Critical":3,"High":2,"Normal":1}.get(r["priority"],0)),reverse=True)
   refs=[];lines=[]
   for r in issues[:5]:
    refs.append({"id":r["id"],"document_id":None,"title":r["title"],"text":r["body"],"date":r["created"][:10],"url":"","position":1,"type":"record","score":1.0})
    lines.append(f"- {r['title']}: {r['body']} Status: {r['status']}; recorded priority: {r['priority']}."+ (f" Due: {r['due']}." if r["due"] else "")+f" [{len(refs)}]")
   return result("These open issues are explicitly recorded in your accessible workspace:\n\n"+"\n\n".join(lines),citations=refs)
  candidates=[]
  for d in scoped:
   options=[]
   for sentence in sentences(d["text"]):
    if len(sentence.split()) < 10 or len(sentence)>650:
     continue
    if re.search(r"\b(concerns?|limitations?|unsupported|not supported|known issues|deprecat|require|risk|must|remaining|failure|troubleshoot)",sentence,re.I):
     if re.search(r"does not (provide|disclose|identify)|no private|not an internal",sentence,re.I):
      continue
     score=3*bool(re.search(r"not supported|cannot|must|only supports?|limit",sentence,re.I))
     score+=bool(re.search(r"SSO|HTTPS|OAuth|authentication|permission|iframe|token|certificate",sentence,re.I))
     score-=4*bool(re.match(r"(This |Your code|To increase|For more|See )",sentence,re.I))
     options.append((score,sentence))
   if options:
    candidates.append((d,max(options,key=lambda x:x[0])[1]))
  candidates.sort(key=lambda p:(p[0]["category"] in {"Known limitations","Troubleshooting"},"concern" in p[1].lower()),reverse=True)
  selected=[];lines=[]
  for d,sentence in candidates[:3]:
   selected.append(d);lines.append(f"- {d['title']}: {sentence} [{len(selected)}]")
  answer="No current open issue or confirmed upcoming blocker is recorded in the accessible work updates. That is different from saying there are no challenges.\n\n"
  if lines:answer+="The sources do discuss these limitations or concerns:\n\n"+"\n\n".join(lines)+"\n\nThese come from dated documentation and historical publications; they are not confirmed live problems in your team."
  else:answer+="The collected sources do not establish the next challenge. A current issue report or roadmap would be needed."
  return result(answer,selected,mode="Recorded status + source context")
