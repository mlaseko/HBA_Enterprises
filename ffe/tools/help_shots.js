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
  ['items', `/p/${pid}/items?room=${kit}`],
  ['items-table', `/p/${pid}/items?view=table&category=Tiles`],
  ['items-list', `/p/${pid}/items?view=list`, async p => { await p.click('th[data-sort]:has-text("Rooms")'); await p.click('th[data-sort]:has-text("Rooms")'); await p.waitForTimeout(200); }],
  ['item-new', `/p/${pid}/items/new?room=${liv}`],
  ['item-edit', `/p/${pid}/items/${ids.sofa}`],
  ['suppliers', `/p/${pid}/suppliers`],
  ['supplier', `/suppliers/${ids.sups['Foshan Tile Co.']}?project=${pid}`, async p => { await p.evaluate(() => { const c = document.getElementById('slink'); if (c) c.textContent = c.textContent.replace(/^https?:\/\/[^/]+/, 'https://hba-interiors.example'); }); }],
  ['payments', `/p/${pid}/payments`],
  ['packing', `/p/${pid}/cartons`],
  ['import', `/p/${pid}/import`],
  ['import-preview', `/p/${pid}/import`, async p => { await p.setInputFiles('input[name=file]', ids.edited_xlsx); await Promise.all([p.waitForNavigation(), p.click('form[enctype] button.btn')]); await p.waitForLoadState('networkidle'); }],
  ['settings', '/settings'],
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
  ['phone-help', `/p/${pid}/items`, async p => { await p.click('#help-btn'); await p.waitForTimeout(450); }],
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
  // the price row of the item form, cropped
  await s.page.goto(`${base}/p/${pid}/items/${ids.sofa}`); await s.page.waitForLoadState('networkidle');
  const grid = s.page.locator('.eyebrow:has-text("Quantity & price") + .grid');
  await grid.screenshot({ path: `${out}/item-price.png` }); console.log('shot item-price');
  await s.ctx.close();
  s = await session(390, 844, true);
  await shoot(s.page, PHONE);
  await s.ctx.close();
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
