// Screenshots for the user guide. Run through tools/help_shots.py, which seeds the demo and starts the server:
//   node tools/help_shots.js <base url> <png dir> <ids.json> <password>
// Desktop pictures are 1366x850 viewports; phone pictures are 390x844 at 2x. Each entry: name, path, optional actions.
const { chromium } = require('playwright');
const fs = require('fs');
const [base, out, idsPath, password] = process.argv.slice(2);
const ids = JSON.parse(fs.readFileSync(idsPath, 'utf8'));
const pid = ids.pid, kit = ids.rooms['GF-KIT'], liv = ids.rooms['GF-LIV'], ground = ids.plans['Ground'];
const exe = process.env.HELP_SHOTS_CHROME || undefined;

const DESKTOP = [
  ['projects', '/'],
  ['overview', `/p/${pid}`],
  ['documents', `/p/${pid}`, async p => { await p.evaluate(() => document.getElementById('documents').scrollIntoView({ block: 'start' })); }],
  ['rooms', `/p/${pid}/rooms`],
  ['rooms-entry', `/p/${pid}/rooms`, async p => { await p.click('details.card summary:has-text("Kitchen")'); await p.waitForTimeout(500); await p.evaluate(() => { const d = document.querySelector('details[open] .room-zoom'); if (d) d.scrollIntoView({ block: 'center' }); }); }],
  ['images', `/p/${pid}/images`],
  ['pdf-pages', `/p/${pid}/images/sets/${ids.set2}`],
  ['plan-browse', `/p/${pid}/plan?plan=${ground}&room=${kit}`],
  ['plan-mark', `/p/${pid}/plan?plan=${ground}&mode=mark`],
  ['plan-match', `/p/${pid}/plan/match?plan=${ids.ref_plan}`],
  ['plan-reference', `/p/${pid}/plan/match?plan=${ids.ref_plan}`, async p => { await p.click('#match button.btn'); await p.waitForTimeout(400); await Promise.all([p.waitForNavigation(), p.click('#app-dialog [data-dialog-yes]')]); await p.waitForLoadState('networkidle'); await p.waitForTimeout(300); }],
  ['items', `/p/${pid}/items?room=${kit}`],
  ['items-table', `/p/${pid}/items?view=table&category=Tiles`],
  ['items-search', `/p/${pid}/items?view=table`, async p => { await p.fill('#live-q', 'tile warm'); await p.waitForTimeout(400); }],
  ['items-floor', `/p/${pid}/items?view=table&floor=Ground`],
  ['items-list', `/p/${pid}/items?view=list`, async p => { await p.click('th[data-sort]:has-text("Rooms")'); await p.click('th[data-sort]:has-text("Rooms")'); await p.waitForTimeout(200); }],
  ['items-select', `/p/${pid}/items?view=table&category=Tiles`, async p => { await p.locator('input.sel-box').nth(0).check(); await p.locator('input.sel-box').nth(2).check(); await p.waitForTimeout(200); }],
  ['items-codes', `/p/${pid}/items?view=table&category=Tiles`, async p => { const codes = await p.$$eval('input.sel-box', xs => xs.slice(0, 3).map(x => x.dataset.codes).join(', ')); await p.click('.select-bar .by-codes'); await p.fill('.select-bar textarea', codes + ', GF-LIV-99'); await p.click('.select-bar .apply'); await p.waitForTimeout(300); }],
  ['viewer', `/p/${pid}/plan?plan=${ground}`, async p => { await p.click('.page-head .actions a[href^="/media/"]'); await p.waitForTimeout(1500); }],
  ['item-new', `/p/${pid}/items/new?room=${liv}`],
  ['item-edit', `/p/${pid}/items/${ids.sofa}`],
  ['buying', `/p/${pid}/buying`],
  ['buying-schedule', `/p/${pid}/buying/schedule`],
  ['suppliers', `/p/${pid}/suppliers`],
  ['supplier', `/suppliers/${ids.sups['Foshan Tile Co.']}?project=${pid}`, async p => { await p.evaluate(() => { const c = document.getElementById('slink'); if (c) c.textContent = c.textContent.replace(/^https?:\/\/[^/]+/, 'https://hba-interiors.example'); }); }],
  ['payments', `/p/${pid}/payments`],
  ['packing', `/p/${pid}/cartons`],
  ['import', `/p/${pid}/import`],
  ['import-preview', `/p/${pid}/import`, async p => { await p.setInputFiles('input[name=file]', ids.edited_xlsx); await Promise.all([p.waitForNavigation(), p.click('form[enctype] button.btn')]); await p.waitForLoadState('networkidle'); }],
  ['settings', '/settings'],
  ['settings-sheets', '/settings#sheets', async p => { await p.evaluate(() => document.getElementById('sheets').scrollIntoView({ block: 'start' })); }],
  ['clip', '/clip'],
  ['client', `/c/${ids.token}`],
  ['client-plan', `/c/${ids.token}?room=${kit}`, async p => { await p.evaluate(() => document.getElementById('plan-section').scrollIntoView({ block: 'start' })); }],
  ['supplier-link', `/s/${ids.stoken}`],
  ['help-drawer', `/p/${pid}/rooms`, async p => { await p.click('#help-btn'); await p.waitForTimeout(450); }],
];
const PHONE = [
  ['phone-overview', `/p/${pid}`],
  ['phone-more', `/p/${pid}`, async p => { await p.click('nav.bottom button'); await p.waitForTimeout(400); }],
  ['phone-capture', `/p/${pid}/capture`],
  ['phone-drafts', `/p/${pid}/drafts`],
  ['phone-plan', `/p/${pid}/plan?plan=${ground}&room=${kit}`],
  ['phone-items', `/p/${pid}/items?room=${kit}`],
  ['phone-buying', `/p/${pid}/buying/${ids.products['Bedside wall light']}`, async p => { await p.evaluate(() => { document.documentElement.style.scrollBehavior = 'auto'; const q = document.getElementById('quotes'); window.scrollTo(0, q.getBoundingClientRect().top + window.scrollY - 72); }); await p.waitForTimeout(400); }],
  ['phone-help', `/p/${pid}/items`, async p => { await p.click('#help-btn'); await p.waitForTimeout(450); }],
  ['phone-order', `/p/${pid}/orders/${ids.orders['Kaiping Sanitary Ware']}`, async p => { await p.evaluate(() => { document.documentElement.style.scrollBehavior = 'auto'; document.getElementById('wechat-box').open = true; const w = document.getElementById('wechat'); window.scrollTo(0, w.getBoundingClientRect().top + window.scrollY - 72); }); await p.waitForTimeout(400); }],
  ['phone-receive', `/p/${pid}/shipments/${ids.shipments[0]}`, async p => { await p.evaluate(() => { document.documentElement.style.scrollBehavior = 'auto'; const b = document.getElementById('boxes'); window.scrollTo(0, b.getBoundingClientRect().top + window.scrollY - 72); }); await p.waitForTimeout(400); }],
];
// pages shown whole: a taller window (name, path, height)
const TALL = [
  ['orders', `/p/${pid}/orders`, 1500],
  ['order', `/p/${pid}/orders/${ids.orders['Kaiping Sanitary Ware']}`, 1240],
  ['tracker', `/p/${pid}/buying/tracker`, 1640],
  ['shipments', `/p/${pid}/shipments`, 1380],
  ['shipment', `/p/${pid}/shipments/${ids.shipments[1]}`, 1290],
  ['lists', `/p/${pid}/lists`, 1180],
];

(async () => {
  const browser = await chromium.launch({ executablePath: exe });
  async function session(w, h, phone) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: phone ? 2 : 1, isMobile: phone, hasTouch: phone });
    const page = await ctx.newPage();
    page.on('pageerror', e => console.log('PAGEERROR', e.message));
    await page.goto(base + '/login'); await page.fill('input[name=password]', password); await page.click('button'); await page.waitForLoadState('networkidle');
    await page.evaluate(() => { try { for (const k of Object.keys(localStorage)) if (k.startsWith('help.seen.')) localStorage.setItem(k, '1'); } catch (e) {} });
    return { ctx, page };
  }
  const only = (process.env.HELP_SHOTS_ONLY || '').split(',').map(x => x.trim()).filter(Boolean);  // regenerate just these pictures
  async function shoot(page, list) {
    for (const [name, path, act] of list) {
      if (only.length && !only.includes(name)) continue;
      await page.goto(base + path); await page.waitForLoadState('networkidle'); await page.waitForTimeout(350);
      await page.evaluate(() => { const n = document.getElementById('help-nudge'); if (n) n.hidden = true; });  // no nudge in the pictures
      if (act) await act(page);
      await page.waitForTimeout(250);
      await page.screenshot({ path: `${out}/${name}.png` });
      console.log('shot', name);
    }
  }
  let s = await session(1366, 850, false);
  await shoot(s.page, DESKTOP);
  // a product bought from two shops, on a taller window: what it asks for, what to order, the quotes and the shops
  if (!only.length || only.includes('buying-product')) {
    await s.page.setViewportSize({ width: 1366, height: 1720 });
    await s.page.goto(`${base}/p/${pid}/buying/${ids.products['Bedside wall light']}`); await s.page.waitForLoadState('networkidle'); await s.page.waitForTimeout(350);
    await s.page.evaluate(() => { const n = document.getElementById('help-nudge'); if (n) n.hidden = true; });
    await s.page.screenshot({ path: `${out}/buying-product.png` }); console.log('shot buying-product');
    await s.page.setViewportSize({ width: 1366, height: 850 });
  }
  for (const [name, path, h] of TALL) {
    if (only.length && !only.includes(name)) continue;
    await s.page.setViewportSize({ width: 1366, height: h });
    await s.page.goto(base + path); await s.page.waitForLoadState('networkidle'); await s.page.waitForTimeout(350);
    await s.page.evaluate(() => { const n = document.getElementById('help-nudge'); if (n) n.hidden = true; });
    await s.page.screenshot({ path: `${out}/${name}.png` }); console.log('shot', name);
  }
  await s.page.setViewportSize({ width: 1366, height: 850 });
  // the quote form, filled in as in the shop, cropped
  if (!only.length || only.includes('buying-quote')) {
    await s.page.setViewportSize({ width: 820, height: 1400 });
    await s.page.goto(`${base}/p/${pid}/buying/${ids.products['Floor tile, large-format porcelain']}#add-quote`); await s.page.waitForLoadState('networkidle');
    await s.page.selectOption('#sup-new', '__new__');
    await s.page.fill('#newshop-new input[name=supplier_name]', 'Nanzhuang Tile Mall'); await s.page.fill('#newshop-new input[name=supplier_city]', 'Foshan - Nanzhuang');
    await s.page.fill('#newshop-new input[name=supplier_wechat]', 'nz_tiles');
    const form = s.page.locator('#add-quote');
    await form.locator('input[name=brand]').fill('Dongpeng'); await form.locator('input[name=model]').fill('DP-6120 Grey');
    await form.locator('input[name=amount]').fill('22.5'); await form.locator('select[name=currency]').selectOption('USD');
    await form.locator('input[name=pack_size]').fill('1.44'); await form.locator('input[name=moq]').fill('30 m²'); await form.locator('input[name=lead_time]').fill('10 days');
    await s.page.evaluate(() => { const n = document.getElementById('help-nudge'); if (n) n.hidden = true; if (document.activeElement) document.activeElement.blur(); });
    await s.page.waitForTimeout(250);
    await form.screenshot({ path: `${out}/buying-quote.png` }); console.log('shot buying-quote');
    await s.page.setViewportSize({ width: 1366, height: 850 });
  }
  await s.ctx.close();
  s = await session(390, 844, true);
  await shoot(s.page, PHONE);
  await s.ctx.close();
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
