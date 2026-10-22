"""Import full official Microsoft docs at pinned historical revisions."""
import json,re,sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
CLIENT=[
("new-teams-desktop-admin.md","Deployment"),("new-teams-deploy-using-policies.md","Deployment"),
("new-teams-bulk-install-client.md","Deployment"),("new-teams-troubleshooting-installation.md","Troubleshooting"),
("new-teams-known-issues.md","Known limitations"),("teams-client-update.md","Deployment"),
("teams-security-guide.md","Security"),("security-compliance-overview.md","Security"),
("teams-architecture-solutions-posters.md","Architecture"),("teams-add-in-for-outlook.md","Integration"),
("prepare-network.md","Networking"),("limits-specifications-teams.md","Known limitations")]
PLATFORM=[
("overview.md","Platform"),("concepts/app-fundamentals-overview.md","Architecture"),
("concepts/design/understand-use-cases.md","App design"),("concepts/design/design-teams-app-overview.md","App design"),
("concepts/authentication/authentication.md","Authentication"),("tabs/what-are-tabs.md","Tabs"),
("tabs/how-to/authentication/tab-sso-overview.md","Authentication"),
("tabs/how-to/authentication/tab-sso-troubleshooting.md","Troubleshooting"),("bots/what-are-bots.md","Bots"),
("bots/how-to/authentication/bot-sso-overview.md","Authentication"),
("messaging-extensions/what-are-messaging-extensions.md","Messaging extensions"),
("apps-in-teams-meetings/teams-apps-in-meetings.md","Meetings"),
("apps-in-teams-meetings/teams-live-share-overview.md","Meetings"),
("graph-api/rsc/resource-specific-consent.md","Permissions"),
("concepts/deploy-and-publish/apps-publish-overview.md","Deployment"),
("concepts/deploy-and-publish/appsource/common-reasons-for-app-validation-failure.md","Known limitations"),
("resources/schema/manifest-schema.md","App manifest"),
("concepts/device-capabilities/browser-device-permissions.md","Permissions"),
("concepts/device-capabilities/native-device-permissions.md","Permissions"),
("tabs/how-to/tab-requirements.md","Known limitations"),
("bots/how-to/conversations/conversation-basics.md","Bots"),
("bots/how-to/conversations/channel-and-group-conversations.md","Bots"),
("task-modules-and-cards/cards/cards-reference.md","Adaptive cards"),
("webhooks-and-connectors/what-are-webhooks-and-connectors.md","Integration"),
("webhooks-and-connectors/how-to/add-incoming-webhook.md","Integration")]
def main():
 server.initialize()
 manifest=[];skipped=[]
 manifest_path=ROOT/"sources/microsoft-manifest.json"
 old=json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
 pinned={d["repository"]:d["revision"] for d in old.get("documents",[])}
 with httpx.Client(timeout=45,follow_redirects=True,headers={"User-Agent":"QUFO-source-import/1.0"}) as client:
  for repo,cutoff,prefix,requested in [("MicrosoftDocs/msteams-docs","2025-06-01","msteams-platform",PLATFORM)]:
   revision=pinned.get(repo)
   if not revision:
    response=client.get(f"https://api.github.com/repos/{repo}/commits",params={"until":cutoff+"T00:00:00Z","per_page":1})
    response.raise_for_status();revision=response.json()[0]["sha"]
   license_response=client.get(f"https://raw.githubusercontent.com/{repo}/{revision}/LICENSE")
   license_response.raise_for_status();license_text=license_response.text
   if "Attribution 4.0" not in license_text and "Creative Commons Attribution" not in license_text:
    raise RuntimeError("Review source license before importing "+repo)
   license_path=ROOT/"sources"/"licenses"/(repo.split("/")[-1]+"-LICENSE.txt")
   license_path.parent.mkdir(exist_ok=True);license_path.write_text(license_text,encoding="utf-8")
   code_license=client.get(f"https://raw.githubusercontent.com/{repo}/{revision}/LICENSE-CODE")
   if code_license.status_code==200:
    (license_path.parent/(repo.split("/")[-1]+"-LICENSE-CODE.txt")).write_text(code_license.text,encoding="utf-8")
   for relative,category in requested:
    path=prefix+"/"+relative
    r=client.get(f"https://raw.githubusercontent.com/{repo}/{revision}/{path}")
    if r.status_code==404:
     skipped.append(path);print("Not in snapshot:",path,flush=True);continue
    r.raise_for_status();raw=r.text
    text=re.sub(r"\A---\s*\n.*?\n---\s*\n","",raw,count=1,flags=re.S)
    text=re.sub(r"<!--.*?-->","",text,flags=re.S)
    text=re.sub(r"!\[([^\]]*)\]\([^)]*\)",r"[Image: \1]",text).strip()
    if len(text.split())<80:skipped.append(path);continue
    heading=re.search(r"^# (.+)$",text,re.M)
    title="Microsoft Teams \u00b7 "+(heading.group(1).strip() if heading else Path(relative).stem.replace("-"," ").title())
    match=re.search(r"^ms\.date:\s*['\"]?(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",raw,re.M)
    source_date=cutoff;date_kind="snapshot"
    if match:
     try:
      value=match.group(1);source_date=server.datetime.strptime(value,"%m/%d/%Y" if "/" in value else "%Y-%m-%d").date().isoformat();date_kind="documentation_updated"
     except ValueError:pass
    url=f"https://github.com/{repo}/blob/{revision}/{path}"
    with server.db() as c:
     uid,duplicate=server.insert_doc(c,title,text,"atharv","Research","company",category,source_date,url,Path(relative).name,raw.encode())
     c.execute("INSERT OR REPLACE INTO doc_metadata VALUES(?,?,?,?,?,?,?)",(uid,"official_documentation",date_kind,repo,revision,"CC-BY-4.0",path))
    manifest.append({"title":title,"source_url":url,"repository":repo,"revision":revision,"source_date":source_date,"date_kind":date_kind,"license":"CC-BY-4.0","words":len(text.split()),"category":category,"modifications":"Search text omits front matter/comments and represents images as alt text; original Markdown retained."})
    print(("Already present: " if duplicate else "Imported: ")+title+f" ({len(text.split())} words)",flush=True)
 (ROOT/"sources/microsoft-manifest.json").write_text(json.dumps({"documents":manifest,"skipped":skipped},ensure_ascii=False,indent=2),encoding="utf-8")
 print(f"Official documents: {len(manifest)}; words: {sum(d['words'] for d in manifest):,}",flush=True)
if __name__=="__main__":main()
