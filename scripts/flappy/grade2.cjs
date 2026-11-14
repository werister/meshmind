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

async function canvasSample(page) {
  // Pixel truth via in-page readback (same-origin inline canvas: never tainted).
  // Returns distinct quantized colors + dominant fraction, or null.
  try {
    return await page.evaluate(() => {
      const c = document.querySelector('canvas');
      if (!c) return null;
      const x = c.getContext('2d');
      const w = c.width, h = c.height;
      if (!w || !h || w > 4000 || h > 4000) return null;
      const d = x.getImageData(0, 0, w, h).data;
      const counts = {};
      let n = 0;
      for (let i = 0; i < d.length; i += 4 * 37) {
        const k = (d[i] >> 5) + ',' + (d[i + 1] >> 5) + ',' + (d[i + 2] >> 5);
        counts[k] = (counts[k] || 0) + 1; n++;
      }
      const vals = Object.values(counts);
      return { distinct: vals.length, topFrac: vals.length ? Math.max(...vals) / n : 1 };
    });
  } catch { return null; }
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
    // visible: sampled EARLY on its own page (fast-dying games show only a
    // static over-screen later). Passes = several colors + changing pixels.
    // Catches blank canvases (falcon-class); text-only voids (artemis-class)
    // can still pass — v2 separates broken/suspicious/real, humans crown.
    let vis = false;
    if (canvas) {
      const browserV = await chromium.launch({ args: ARGS });
      try {
        const pv = await browserV.newPage({ viewport: { width: 480, height: 640 } });
        await pv.setContent(html, { waitUntil: 'load', timeout: 15000 });
        await sleep(150);
        const s1 = await canvasSample(pv);
        await sleep(450);
        const s2 = await canvasSample(pv);
        vis = !!(s1 && s2 && s1.distinct >= 4 &&
                 JSON.stringify(s1) !== JSON.stringify(s2));
        if (!vis) out.notes.push(`visible: ${JSON.stringify(s1)} vs ${JSON.stringify(s2)}`);
      } finally {
        try { await browserV.close(); } catch { /* already dead */ }
      }
    }
    C.visible = vis;
    // ---- L2: hooks ----
    s = await freshPhase(html);
    const h0 = await readHooks(s.page);
    C.hooks = !!(h0 && h0 !== 'eval-threw' && h0.ty === 'number' && h0.ts === 'number' && h0.to === 'boolean');
    if (!C.hooks) out.notes.push('hooks: ' + JSON.stringify(h0));
    await endPhase(s);
    if (C.hooks) {
      // ---- L3: physics (poll for any alive falling step; robust to both
      // fast-fallers that die quickly and slow-fallers that creep) ----
      // y must stay within the world while alive (no thousand-pixel falls).
      s = await freshPhase(html);
      const H3 = await s.page.evaluate(() => { const c = document.querySelector('canvas'); return c ? c.height : 600; });
      let grav = false, prev = null, h1 = null, bounded = true;
      const tG = Date.now() + 1500;
      while (Date.now() < tG) {
        h1 = await readHooks(s.page);
        if (!h1 || h1 === 'eval-threw' || h1.over) break;
        if (h1.y < -50 || h1.y > H3 + 50) { bounded = false; break; }
        if (prev !== null && h1.y > prev + 2) { grav = true; break; }
        prev = h1.y;
        await sleep(100);
      }
      C.gravity = grav && bounded;
      if (!bounded) out.notes.push('physics: bird left the world while alive');
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
      // scores_paced: must score at a human rate (<=2/s sustained);
      // hyper-speed games (10 pipes in 4 s) fail even though they "score".
      let scored = 0, prevY = null, firstScoreAt = 0;
      const tStart = Date.now(), tEnd = tStart + 45000;
      while (Date.now() < tEnd) {
        const h = await readHooks(s.page);
        if (!h || h === 'eval-threw') break;
        if ((h.score || 0) > scored) {
          scored = h.score;
          if (!firstScoreAt) firstScoreAt = Date.now();
          if (scored >= 3) break;
        }
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
      const elapsed = Math.max(1, (Date.now() - tStart) / 1000);
      const rate = scored > 0 ? scored / elapsed : 0;
      C.scores = scored > 0 && rate <= 2.0;
      if (!C.scores) out.notes.push(`score: n=${scored} rate=${rate.toFixed(2)}/s over ${elapsed.toFixed(0)}s`);
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
    const pts = { loads: 5, no_errors: 5, has_canvas: 5, animates: 5, visible: 10,
                  hooks: 10, gravity: 12, flap: 13, scores: 10, gameover: 10, restart: 5 };
    for (const [k, p] of Object.entries(pts)) if (C[k]) out.score += p;
  } catch (e) {
    out.notes.push('GRADER-ERROR: ' + String(e).slice(0, 200));
  }
  out.ms = Date.now() - t0;
  console.log(JSON.stringify(out));
})();
