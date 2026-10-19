// Record only the offline fictional exercise. No operational response is sent.
const {chromium}=require('playwright');
const {copyFile,mkdir}=require('node:fs/promises');
const {execFile}=require('node:child_process');
const {promisify}=require('node:util');
const {resolve}=require('node:path');
let browser;

(async()=>{
 await mkdir('public/recordings',{recursive:true});
 browser=await chromium.launch({headless:true,channel:'msedge'});
 const record=async(name,actions)=>{
  const context=await browser.newContext({viewport:{width:1920,height:1080},recordVideo:{dir:'out/capture',size:{width:1920,height:1080}}});
  const page=await context.newPage();
  await page.goto('http://127.0.0.1:8000/ui/');
  await page.locator('#timeline').waitFor();
  await actions(page);
  const video=page.video();await context.close();
  await copyFile(await video.path(),`public/recordings/${name}.webm`);
  const encoder=process.env.ARGUS_TRAILER_FFMPEG || resolve('node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe');
  await promisify(execFile)(encoder,['-v','error','-y','-i',`public/recordings/${name}.webm`,'-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',`public/recordings/${name}.mp4`]);
  console.log(`Recorded ${name}`);
 };
 if(!process.argv.includes('--review-only')) await record('replay',async p=>{
  await p.locator('#timeline').fill('0');await p.locator('#timeline').dispatchEvent('input');
  await p.locator('#replay-speed').selectOption('120');
  await p.waitForTimeout(1000);await p.locator('#play').click();await p.waitForTimeout(2500);await p.locator('#play').click();
  await p.locator('#timeline').fill('1680');await p.locator('#timeline').dispatchEvent('input');await p.locator('#play').click();
  await p.waitForTimeout(10000);await p.locator('#play').click();
  await p.locator('#timeline').fill('3000');await p.locator('#timeline').dispatchEvent('input');await p.locator('#play').click();await p.waitForTimeout(3500);await p.locator('#play').click();
  await p.locator('#timeline').fill('4800');await p.locator('#timeline').dispatchEvent('input');await p.locator('#play').click();await p.waitForTimeout(3500);await p.locator('#play').click();
  await p.locator('#jump-alert').click();await p.waitForTimeout(3500);
 });
 await record('review',async p=>{
  await p.waitForTimeout(1200);
  await p.getByRole('button',{name:'Review evidence',exact:true}).click();await p.waitForTimeout(3000);
  await p.getByRole('button',{name:'Close evidence',exact:true}).click();
  await p.getByRole('button',{name:/Review response/}).click();await p.waitForTimeout(1600);
  await p.getByRole('radio',{name:/VHF/}).check();await p.waitForTimeout(1000);
  await p.locator('#confirm-review').check();await p.waitForTimeout(1500);
  await p.locator('#confirm-approve').click();await p.waitForTimeout(2000);
  await p.waitForTimeout(3000);
  await p.screenshot({path:'public/approved-review.png'});
 });
 await browser.close();
})().catch(async error=>{console.error(error);if(browser)await browser.close();process.exitCode=1;});
