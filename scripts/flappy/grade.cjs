// Flappy Bird grader: headless checks on one model-generated HTML file.
// Usage: node grade.cjs <htmlfile>   -> JSON result on stdout.
// Rubric (100): L1 boot 20 | L2 hooks 15 | L3 physics 25 | L4 game 30 (L0 static 10 by caller).
// Notes: one browser launch per phase (single-process headless-shell dies when its
// last page closes); animation proven by rAF liveness + hook deltas, not pixels
// (compositor frames freeze in this headless mode; verified 2026-11-14).
const { chromium } = require('playwright');
const fs = require('fs');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ARGS = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
              '--single-process', '--no-zygote', '--disable-gpu'];

async function freshPhase(html) {
  const browser = await chromium.launch({ args: ARGS });
  const page = await browser.newPage({ viewport: { width: 480, height: 640 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + String(e).slice(0, 160)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 160)); });
  await page.setContent(html, { waitUntil: 'load', timeout: 15000 });
  await sleep(400);
  return { browser, page, errors };
}

async function endPhase(s) {
  try { await s.browser.close(); } catch { /* already dead */ }
}

async function readHooks(page) {
  try {
    return await page.evaluate(() => {
      const f = window.__flappy;
      if (!f || typeof f !== 'object') return null;
      return { y: f.y, score: f.score, over: f.over,
               ty: typeof f.y, ts: typeof f.score, to: typeof f.over };
    });
  } catch { return 'eval-threw'; }
}

async function rafAlive(page) {
  try {
    await page.evaluate(() => {
      window.__probe_n = 0;
      requestAnimationFrame(function f() { window.__probe_n++; requestAnimationFrame(f); });
    });
    await sleep(700);
    const n = await page.evaluate(() => window.__probe_n);
    return typeof n === 'number' && n >= 5;
  } catch { return false; }
}

(async () => {
  const out = { file: process.argv[2], checks: {}, score: 0, ms: 0, notes: [] };
  const t0 = Date.now();
  const C = out.checks;
  try {
    const html = fs.readFileSync(process.argv[2], 'utf8');
    // ---- L1: boot ----
    let s = await freshPhase(html);
    const canvas = await s.page.$('canvas');
    C.loads = true;
    C.no_errors = s.errors.length === 0;
    if (!C.no_errors) out.notes.push(s.errors[0]);
    C.has_canvas = !!canvas;
    C.animates = canvas ? await rafAlive(s.page) : false;
    await endPhase(s);
    // ---- L2: hooks ----
    s = await freshPhase(html);
    const h0 = await readHooks(s.page);
    C.hooks = !!(h0 && h0 !== 'eval-threw' && h0.ty === 'number' && h0.ts === 'number' && h0.to === 'boolean');
    if (!C.hooks) out.notes.push('hooks: ' + JSON.stringify(h0));
    await endPhase(s);
    if (C.hooks) {
      // ---- L3: physics (poll for any alive falling step; robust to both
      // fast-fallers that die quickly and slow-fallers that creep) ----
      s = await freshPhase(html);
      let grav = false, prev = null, h1 = null;
      const tG = Date.now() + 1500;
      while (Date.now() < tG) {
        h1 = await readHooks(s.page);
        if (!h1 || h1 === 'eval-threw' || h1.over) break;
        if (prev !== null && h1.y > prev + 2) { grav = true; break; }
        prev = h1.y;
        await sleep(100);
      }
      C.gravity = grav;
      // flap must be measured on a LIVE bird: revive first if polling killed it
      if (!h1 || h1 === 'eval-threw' || h1.over) {
        const bx = await (await s.page.$('canvas')).boundingBox();
        await s.page.mouse.click(bx.x + bx.width / 2, bx.y + bx.height / 2);
        await sleep(250);
        await s.page.keyboard.press('r');
        await sleep(250);
        h1 = await readHooks(s.page);
      }
      await s.page.keyboard.press('Space');
      await sleep(280);
      const h2 = await readHooks(s.page);
      C.flap = !!(h2 && h2 !== 'eval-threw') && !h2.over && h1 && h1 !== 'eval-threw' && h2.y < h1.y - 2;
      if (!C.gravity) out.notes.push('gravity: no falling step seen' + (h1 && h1 !== 'eval-threw' ? ` last y=${h1.y} over=${h1.over}` : ''));
      if (!C.flap) out.notes.push('flap: no rise after Space');
      await endPhase(s);
      // ---- L4a: score under autopilot ----
      s = await freshPhase(html);
      const H = await s.page.evaluate(() => { const c = document.querySelector('canvas'); return c ? c.height : 600; });
      const cbox = await (await s.page.$('canvas')).boundingBox();
      let scored = 0, prevY = null;
      const tEnd = Date.now() + 45000;
      while (Date.now() < tEnd) {
        const h = await readHooks(s.page);
        if (!h || h === 'eval-threw') break;
        scored = Math.max(scored, h.score || 0);
        if (scored > 0) break;
        if (h.over) {
          await s.page.mouse.click(cbox.x + cbox.width / 2, cbox.y + cbox.height / 2);
          await sleep(300);
          await s.page.keyboard.press('r');
          await sleep(300);
          prevY = null;
          continue;
        }
        const dy = prevY === null ? 0 : h.y - prevY;
        if (h.y > H * 0.5 || dy > 15) await s.page.keyboard.press('Space');
        prevY = h.y;
        await sleep(250);
      }
      C.scores = scored > 0;
      if (!C.scores) out.notes.push(`score0: last score=${scored}`);
      await endPhase(s);
      // ---- L4b: game over with no input ----
      s = await freshPhase(html);
      let died = false;
      const tEnd2 = Date.now() + 30000;
      while (Date.now() < tEnd2) {
        const h = await readHooks(s.page);
        if (!h || h === 'eval-threw') break;
        if (h.over) { died = true; break; }
        await sleep(500);
      }
      C.gameover = died;
      // ---- L4c: restart (same page) ----
      let restarted = false, sc = -1;
      if (died) {
        const box = await (await s.page.$('canvas')).boundingBox();
        await s.page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
        await sleep(250);
        await s.page.keyboard.press('r');
        await sleep(250);
        const h = await readHooks(s.page);
        if (h && h !== 'eval-threw') { restarted = h.over === false; sc = h.score; }
      }
      C.restart = restarted && sc === 0;
      if (!C.restart) out.notes.push(`restart: restarted=${restarted} score=${sc}`);
      await endPhase(s);
    } else {
      C.gravity = C.flap = C.scores = C.gameover = C.restart = false;
    }
    const pts = { loads: 5, no_errors: 5, has_canvas: 5, animates: 5, hooks: 15,
                  gravity: 12, flap: 13, scores: 10, gameover: 10, restart: 10 };
    for (const [k, p] of Object.entries(pts)) if (C[k]) out.score += p;
  } catch (e) {
    out.notes.push('GRADER-ERROR: ' + String(e).slice(0, 200));
  }
  out.ms = Date.now() - t0;
  console.log(JSON.stringify(out));
})();
