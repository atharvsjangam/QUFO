if (!process.env.QUFO_PASSWORD) throw new Error('Set QUFO_PASSWORD to your workspace password');
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 let healthy=false;
 for(let i=0;i<30;i++){
  try{healthy=(await fetch('http://127.0.0.1:8765/api/health')).ok;if(healthy)break;}catch{}
  await new Promise(r=>setTimeout(r,300));
 }
 assert(healthy,'QUFO did not become ready');
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1050}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto('http://127.0.0.1:8765');
  await page.locator('#password').fill(process.env.QUFO_PASSWORD);
  await page.locator('#login button[type=submit]').click();
  await page.locator('[data-page=chat]').waitFor();
  await page.getByText('27 source documents',{exact:true}).waitFor();
  await page.screenshot({path:'docs/screenshots/overview.png',fullPage:true});
  await page.locator('[data-page=chat]').click();
  for(const [q,expected] of [
   ['when did it start','do not establish when development'],
   ['when did the development start','public announcement date'],
   ['what was the last major update','2023-10-05'],
   ['what is the next problem we are facing','No current open issue'],
   ['upcoming challenges','dated documentation']]){
   const n=await page.locator('.message.assistant').count();
   await page.locator('#question').fill(q);await page.locator('#ask button').click();
   await page.locator('.message.assistant').nth(n).waitFor({timeout:60000});
   assert((await page.locator('.message.assistant .answer').nth(n).innerText()).includes(expected),q);
  }
  await page.screenshot({path:'docs/screenshots/conversation.png',fullPage:true});
  await page.locator('#new-conversation').click();
  await page.locator('.message').first().waitFor({state:'hidden'});
  assert.equal(await page.locator('.message').count(),0);
  await page.locator('[data-page=knowledge]').click();
  const card=page.locator('.doc-card').filter({has:page.getByRole('heading',{name:'Microsoft Teams · Resource-specific consent for your Teams app',exact:true})});
  await card.getByRole('button',{name:'Open document'}).click();
  await page.getByText('Full official Microsoft documentation',{exact:false}).waitFor();
  await page.screenshot({path:'docs/screenshots/full-document.png',fullPage:true});
  await page.locator('.close').click();
  await page.locator('[data-page=chat]').click();
  await page.locator('#question').fill("How does resource-specific consent limit an app's permissions?");
  const started=Date.now();await page.locator('#ask button').click();
  await page.locator('.message.assistant').waitFor({timeout:120000});
  const answer=await page.locator('.message.assistant .answer').innerText();
  const mode=await page.locator('.message.assistant .eyebrow').innerText();
  assert(/consent|permission/i.test(answer));
  assert((await page.locator('.citation-chips button').count())>0);
  await page.screenshot({path:'docs/screenshots/expanded-chat.png',fullPage:true});
  fs.writeFileSync('data/expanded-chat-check.json',JSON.stringify({mode,answer,seconds:(Date.now()-started)/1000},null,2));
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Chat overflows on mobile');
  assert.deepEqual(errors,[]);
  console.log('Expanded-corpus browser checks passed: exact reported questions, reset, full source attribution, technical answer with evidence, mobile chat. Answer mode: '+mode);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
