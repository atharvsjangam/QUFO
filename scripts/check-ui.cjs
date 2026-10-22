if (!process.env.QUFO_PASSWORD) throw new Error('Set QUFO_PASSWORD to your workspace password');
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1050},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8765');
 await page.locator('#username').fill('atharv');
 await page.locator('#password').fill(process.env.QUFO_PASSWORD);
 await page.locator('#login button[type=submit]').click();
 await page.getByRole('heading',{name:'A little context. A lot of clarity.'}).waitFor();
 await page.evaluate(async()=>{
  const w=await(await fetch('/api/workspace')).json();
  for(const r of w.records.filter(r=>r.title==='Browser contribution verification')){
   await fetch('/api/records/'+r.id,{method:'DELETE'});
  }
  for(const d of w.documents.filter(d=>d.title==='Browser verification evidence')){
   await fetch('/api/documents/'+d.id,{method:'DELETE'});
  }
 });
 await page.reload();await page.getByRole('heading',{name:'A little context. A lot of clarity.'}).waitFor();

 const out=path.resolve('docs/screenshots');fs.mkdirSync(out,{recursive:true});
 await page.screenshot({path:path.join(out,'overview.png'),fullPage:true});
 for(const [name,title] of [['knowledge','The knowledge library.'],['contributions','Every point has a place.'],['reports','A perspective for every person.'],['chat','Ask a better-informed question.']]){
  await page.locator('[data-page='+name+']').click();
  await page.getByRole('heading',{name:title,exact:true}).waitFor();
  await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
 }
 await page.locator('[data-page=knowledge]').click();
 await page.getByRole('button',{name:'Upload document',exact:true}).click();
 await page.locator('input[type=file]').setInputFiles({name:'QUFO-browser-check.txt',mimeType:'text/plain',buffer:Buffer.from('The QUFO browser verification completed an upload. This testing document verifies that retained evidence is readable.')});
 await page.locator('#f-title').fill('Browser verification evidence');
 await page.locator('#upload-form button[type=submit]').click();
 await page.locator('#modal').waitFor({state:'hidden'});
 await page.getByRole('heading',{name:'Browser verification evidence',exact:true}).waitFor();
 const uploaded=await page.evaluate(async()=>{const w=await (await fetch('/api/workspace')).json();return w.documents.find(d=>d.title==='Browser verification evidence').id;});
 await page.evaluate(async id=>{await fetch('/api/documents/'+id,{method:'DELETE'});},uploaded);
 await page.locator('[data-page=contributions]').click();
 await page.getByRole('button',{name:'Add contribution',exact:true}).click();
 await page.locator('#f-title').fill('Browser contribution verification');
 await page.locator('#f-body').fill('Verified contribution form submission, visibility and explicit completion status.');
 await page.locator('#f-kind').selectOption('Task');
 await page.locator('#f-status').selectOption('Completed');
 await page.locator('#record-form button[type=submit]').click();
 await page.locator('#modal').waitFor({state:'hidden'});
 await page.getByRole('button',{name:'Browser contribution verification',exact:true}).waitFor();
 await page.getByRole('button',{name:'Browser contribution verification',exact:true}).click();
 await page.locator('#f-status').selectOption('In progress');
 await page.locator('#record-form button[type=submit]').click();
 await page.locator('#modal').waitFor({state:'hidden'});
 await page.locator('[data-page=reports]').click();
 await page.locator('#audience').selectOption('Investors');
 await page.locator('#update-report').click();
 await page.getByText('Documented milestones, business context, and recorded costs.',{exact:false}).waitFor();
 await page.getByRole('button',{name:'Review & export'}).click();
 await page.locator('[name=document_ids]').first().check();
 await page.locator('[name=approved]').check();
 const downloadPromise=page.waitForEvent('download');
 await page.locator('#export-form button[type=submit]').click();
 const download=await downloadPromise;assert.equal(download.suggestedFilename(),'QUFO-briefing.md');
 await page.evaluate(async()=>{
  const w=await(await fetch('/api/workspace')).json();
  for(const r of w.records.filter(r=>r.title==='Browser contribution verification')){
    await fetch('/api/records/'+r.id,{method:'DELETE'});
  }
 });
 await page.reload();
 await page.locator('[data-page=overview]').waitFor();
 await page.setViewportSize({width:390,height:844});
 await page.locator('[data-page=overview]').click();
 await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'mobile overflow');
 assert.deepEqual(errors,[]);
 await browser.close();
 console.log('Browser workflow passed: login, navigation, upload, contribution, status update, report audience, approved export, mobile layout; no JavaScript errors.');
})().catch(e=>{console.error(e);process.exit(1);});
