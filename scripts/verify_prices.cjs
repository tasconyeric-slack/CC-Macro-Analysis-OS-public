// Development-only acceptance: real public build, two languages and viewport widths.
const {chromium} = require(process.env.CC_PLAYWRIGHT_MODULE || 'playwright-core');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({headless:true,executablePath:process.env.CC_CHROMIUM_PATH || undefined});
  const context = await browser.newContext({acceptDownloads:true});
  const page = await context.newPage();
  const errors = []; page.on('pageerror',e=>errors.push(String(e)));
  const dir = path.resolve('docs/design/prices/acceptance'); fs.mkdirSync(dir,{recursive:true});
  const report = [];
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:width===1440?1000:844});
    for (const locale of ['zh','en']) {
      await page.goto((process.env.CC_PRICES_BASE || 'http://localhost:8765')+'/'+locale+'/data-prices.html',{waitUntil:'networkidle'});
      const overflow = await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
      if (overflow) throw Error('page overflow: '+locale+' '+width);
      await page.screenshot({path:path.join(dir,`${locale}-${width}.png`)});
      const chain = page.locator('#price-chain');
      const colors=await chain.locator('[data-range-plot="all"] .data-plot-wide path.series').evaluateAll(lines=>lines.map(line=>getComputedStyle(line).stroke));
      if(new Set(colors).size!==3) throw Error('composite series colors are not distinct');
      for (const range of ['2y','5y','all']) {
        await chain.locator(`[data-range="${range}"]`).click();
        if (await chain.locator(`[data-range="${range}"]`).getAttribute('aria-pressed')!=='true') throw Error('range state');
        if (!await chain.locator(`[data-range-plot="${range}"]`).isVisible()) throw Error('range plot');
      }
      await page.locator('#price-month').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(dir,`${locale}-${width}-table.png`)});
      const metric = page.locator('#metric-cn_cpi_food_yoy');
      await metric.scrollIntoViewIfNeeded();
      await metric.locator('[data-range="2y"]').click();
      await metric.locator('summary').click();
      if (!await metric.locator('details[open]').count()) throw Error('metric anchor/details');
      if (!await metric.locator('a[href*="stats.gov.cn"]').count()) throw Error('original NBS link');
      await page.screenshot({path:path.join(dir,`${locale}-${width}-detail.png`)});
      for (const href of ['../data/prices.xlsx','../data/prices-chain.csv','../data/series/cn_cpi_food_yoy.csv']) {
        const response=await context.request.get(new URL(href,page.url()).href);
        if (!response.ok() || (await response.body()).length<50) throw Error('export '+href);
      }
      const rows = await page.locator('#price-month tbody tr').count();
      if(rows!==28) throw Error('Expected 28 monthly price series, got '+rows);
      report.push({locale,width,overflow,rows,rangeSwitch:'passed',metricDetail:'passed',exports:'passed'});
    }
  }
  if(errors.length) throw Error(errors.join('\n'));
  fs.writeFileSync(path.join(dir,'browser-checks.json'),JSON.stringify({report,errors},null,2)+'\n');
  console.log(JSON.stringify({report,errors}));
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
