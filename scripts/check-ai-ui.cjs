if (!process.env.QUFO_PASSWORD) throw new Error('Set QUFO_PASSWORD to your workspace password');
const {chromium}=require('playwright');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1050}});
 try{
  await page.goto('http://127.0.0.1:8765');
  await page.locator('#password').fill(process.env.QUFO_PASSWORD);
  await page.locator('#login button[type=submit]').click();
  await page.locator('[data-page=chat]').waitFor();
  await page.locator('[data-page=chat]').click();
  await page.locator('#question').fill('What architecture changes were made to Microsoft Teams?');
  await page.locator('#ask button').click();
  await page.locator('.message.assistant').waitFor({timeout:120000});
  const mode=await page.locator('.message.assistant .eyebrow').innerText();
  const answer=await page.locator('.message.assistant .answer').innerText();
  if(!mode.toLowerCase().includes('ai synthesis'))throw Error('Expected real generated synthesis, got '+mode);
  if(!answer.includes('WebView2')&&!answer.includes('React'))throw Error('Expected documented architecture details');
  await page.screenshot({path:'docs/screenshots/chat-answer.png',fullPage:true});
  await page.locator('.citation-chips button').first().click();
  await page.getByRole('heading',{name:'Connected knowledge'}).waitFor();
  await page.screenshot({path:'docs/screenshots/evidence.png',fullPage:true});
  console.log('Real AI browser check passed: generated architecture answer, citations, evidence viewer, connected documents.');
  fs.writeFileSync('data/browser-ai-check.json',JSON.stringify({mode,answer,passed:true},null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
