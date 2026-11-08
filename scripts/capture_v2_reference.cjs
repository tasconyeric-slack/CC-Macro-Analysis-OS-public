// Development-only reference measurements; never included in the static site.
const {chromium} = require(process.env.CC_PLAYWRIGHT_MODULE || 'playwright-core');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CC_CHROMIUM_PATH || undefined, args:['--remote-debugging-port=9339']});
  for(const [name,url] of [['guojin','https://sunyongle.cn/'],['cmm','https://chinamacromonitor.com/']]) {
    const dir=path.resolve('docs/design/v2/reference',name); fs.mkdirSync(dir,{recursive:true});
    const context=await browser.newContext({viewport:{width:1440,height:900},recordHar:{path:path.join(dir,'capture.har'),content:'omit'}});
    const page=await context.newPage();
    try {
      await page.goto(url,{waitUntil:'networkidle',timeout:60000});
      await page.screenshot({path:path.join(dir,'desktop.png')});
      await page.screenshot({path:path.join(dir,'full.png'),fullPage:true});
      const measurements=await page.evaluate(()=>({title:document.title,url:location.href,viewport:{width:innerWidth,height:innerHeight},nodes:[...document.querySelectorAll('header,main,h1,h2,h3,section,a')].filter(e=>e.getBoundingClientRect().width>100).slice(0,100).map(e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return {tag:e.tagName,classes:e.className,text:e.textContent.trim().slice(0,80),x:r.x,y:r.y,width:r.width,height:r.height,font:s.fontFamily,size:s.fontSize,weight:s.fontWeight,lineHeight:s.lineHeight,color:s.color,background:s.backgroundColor,padding:s.padding,gap:s.gap,grid:s.gridTemplateColumns,radius:s.borderRadius,shadow:s.boxShadow}}),scripts:[...document.scripts].map(x=>x.src).filter(Boolean)}));
      fs.writeFileSync(path.join(dir,'measurements.json'),JSON.stringify(measurements,null,2));
      await page.locator('a').filter({hasText:/进入专栏|数据|Data/}).first().hover().catch(()=>{});
      await page.screenshot({path:path.join(dir,'hover.png')});
      await page.keyboard.press('Tab'); await page.screenshot({path:path.join(dir,'focus.png')});
      await page.setViewportSize({width:390,height:844}); await page.screenshot({path:path.join(dir,'mobile.png')});
      console.log(JSON.stringify({name,url:page.url(),title:await page.title()}));
    } catch(e) {fs.writeFileSync(path.join(dir,'capture-error.txt'),String(e)); console.log(name+' '+e.message);}
    await context.close();
  }
  const context=await browser.newContext({viewport:{width:1440,height:900}});
  for(const url of ['https://sunyongle.cn/','https://chinamacromonitor.com/']){const p=await context.newPage(); await p.goto(url,{waitUntil:'domcontentloaded',timeout:60000}).catch(()=>{});}
  console.log('REA ready on 9339');
  process.on('SIGINT',async()=>{await browser.close();process.exit(0)});
  setInterval(()=>{},30000);
})();
