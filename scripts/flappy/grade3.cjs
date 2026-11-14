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
      // ---- L3: physics, control-treatment design (v3) ----
      // Control: no input for ~450ms — must show FALLING (dy > +3) while alive
      // and stay in-bounds. Treatment: Space (then click as fallback) must show
      // a real RISE (dy < -8 within 400ms) — the opposite sign, so background
      // drift can never pass as input response (v1/v2 false-positive class).
      s = await freshPhase(html);
      const H3 = await s.page.evaluate(() => { const c = document.querySelector('canvas'); return c ? c.height : 600; });
      async function sampleY() {
        const h = await readHooks(s.page);
        return (h && h !== 'eval-threw') ? h : null;
      }
      // Start-sequence: dismiss tap-to-start screens (Space AND click + settle;
      // click-only games are spec-legal). Harmless for auto-starters (a flap,
      // then it falls — what we observe).
      await s.page.keyboard.press('Space'); await sleep(200);
      {
        const bx0 = await (await s.page.$('canvas')).boundingBox();
        await s.page.mouse.click(bx0.x + bx0.width / 2, bx0.y + bx0.height / 2);
      }
      await sleep(300);
      let c0 = await sampleY(); await sleep(150);
      let c1 = await sampleY(); await sleep(150);
      let c2 = await sampleY();
      const inB = (h) => h && h.y >= -50 && h.y <= H3 + 50;
      const aliveFall = c0 && c1 && c2 && !c0.over && !c1.over && !c2.over &&
                        inB(c0) && inB(c1) && inB(c2) && (c2.y - c0.y) > 3;
      // Fast-faller rule: died during control AT the ground = real gravity
      // (fell to the floor within ~600ms); died mid-screen = no-floor class.
      const cLast = c2 || c1 || c0;
      const fastFall = cLast && cLast.over &&
        [c0, c1, c2].filter(Boolean).some((h) => !h.over) &&
        cLast.y >= H3 - 150 && cLast.y <= H3 + 100;
      C.gravity = !!(aliveFall || fastFall);
      if (!C.gravity) out.notes.push(`gravity: control=[${c0 && Math.round(c0.y)},${c1 && Math.round(c1.y)},${c2 && Math.round(c2.y)}] over=${c2 && c2.over} H=${H3}`);
      // Treatment on a LIVE bird (revive first if control killed it).
      let t0 = c2;
      if (!t0 || t0.over) {
        const bx = await (await s.page.$('canvas')).boundingBox();
        await s.page.mouse.click(bx.x + bx.width / 2, bx.y + bx.height / 2);
        await sleep(250);
        await s.page.keyboard.press('r');
        await sleep(250);
        t0 = await sampleY();
      }
      // Apex-tracked rise: poll 50ms x 400ms after input, take min-y.
      // (A single sample at 400ms misses the apex — the bird has fallen back
      // past start by then in normal physics; ref-good's apex is ~-30px.)
      async function flapResponds(act) {
        const a = await sampleY();
        if (!a || a.over) return false;
        if (act === 'space') await s.page.keyboard.press('Space');
        else {
          const bx = await (await s.page.$('canvas')).boundingBox();
          await s.page.mouse.click(bx.x + bx.width / 2, bx.y + bx.height / 2);
        }
        let minY = a.y;
        const tA = Date.now() + 400;
        while (Date.now() < tA) {
          const b = await sampleY();
          if (!b || b.over) break;
          if (b.y < minY) minY = b.y;
          await sleep(50);
        }
        return (minY - a.y) < -8;
      }
      let flapSpace = false, flapClick = false;
      if (t0 && !t0.over) {
        flapSpace = await flapResponds('space');
        if (!flapSpace) {
          // re-steady, then try click (spec allows either)
          await sleep(300);
          const r = await sampleY();
          if (r && !r.over) flapClick = await flapResponds('click');
        }
      }
      C.flap = flapSpace || flapClick;
      if (!C.flap) out.notes.push('flap: no input response (space+click vs control)');
      await endPhase(s);
      // ---- L4a: INPUT-CAUSAL scoring, two arms back-to-back (same load window)
      // Arm H (hands-off): start, then no input 12s -> scoreH must stay ~0.
      // Arm A (autopilot): start, then play 30s -> scoreA must reach >=2.
      // A game that scores with nobody playing (static-decal bird, gemma4-class)
      // fails even if the autopilot arm also scores: scoreA > 3*scoreH proves
      // the input caused the score. Both arms in one window control for the
      // load-dependent rAF physics found in v2-vs-v3 (delta-time games).
      let H = 600;
      async function startSeq(pg, box) {
        await pg.keyboard.press('Space'); await sleep(200);
        await pg.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
        await sleep(300);
      }
      // Arm H: hands-off
      s = await freshPhase(html);
      H = await s.page.evaluate(() => { const c = document.querySelector('canvas'); return c ? c.height : 600; });
      let cboxH = await (await s.page.$('canvas')).boundingBox();
      await startSeq(s.page, cboxH);
      let scoreH = 0;
      const tEndH = Date.now() + 12000;
      while (Date.now() < tEndH) {
        const h = await readHooks(s.page);
        if (!h || h === 'eval-threw') break;
        if ((h.score || 0) > scoreH) scoreH = h.score;
        await sleep(250);
      }
      await endPhase(s);
      // Arm A: autopilot with click-fallback (click-only games are spec-legal)
      s = await freshPhase(html);
      const cbox = await (await s.page.$('canvas')).boundingBox();
      await startSeq(s.page, cbox);
      let scored = 0, prevY = null, clickMode = false, ySeen = [], lastPress = 0;
      // Flight filter: a life's score counts only if the bird FLEW that life
      // (intra-life y-range > 100px). Static-decal birds (gemma4-class) can get
      // lucky pipes; their scores must not count.
      let effA = 0, curMin = null, curMax = null, curMaxS = 0;
      const tStart = Date.now(), tEnd = tStart + 30000;
      async function autoAct() {
        if (!clickMode) await s.page.keyboard.press('Space');
        else await s.page.mouse.click(cbox.x + cbox.width / 2, cbox.y + cbox.height / 2);
      }
      while (Date.now() < tEnd) {
        const h = await readHooks(s.page);
        if (!h || h === 'eval-threw') break;
        if ((h.score || 0) > scored) {
          scored = h.score;
          if (scored >= 3) break;
        }
        if (h.over) {
          if (curMin !== null && curMax - curMin > 100 && curMaxS > effA) effA = curMaxS;
          curMin = curMax = null; curMaxS = 0;
          await s.page.mouse.click(cbox.x + cbox.width / 2, cbox.y + cbox.height / 2);
          await sleep(250);
          await s.page.keyboard.press('r');
          await sleep(250);
          await s.page.keyboard.press('Space');
          await sleep(250);
          prevY = null;
          continue;
        }
        if (curMin === null) { curMin = curMax = h.y; }
        else { if (h.y < curMin) curMin = h.y; if (h.y > curMax) curMax = h.y; }
        if ((h.score || 0) > curMaxS) curMaxS = h.score;
        // click-fallback: 3s of Space with a frozen bird -> switch to clicks
        ySeen.push(h.y);
        if (!clickMode && Date.now() - tStart > 3000 && ySeen.length > 10) {
          const w = ySeen.slice(-10);
          if (Math.max(...w) - Math.min(...w) < 2 && scored === 0) {
            clickMode = true;
            out.notes.push('autopilot: space frozen, switched to click-mode');
          }
        }
        const dy = prevY === null ? 0 : h.y - prevY;
        // Classic flappy law: press only when FALLING below the hover line,
        // rate-limited. Chained presses pin vy at flap velocity and ride the
        // bird into the top pipes (regression root cause, probe [DBG-flap1]).
        if (dy > 0 && h.y > H * 0.45 && Date.now() - lastPress > 180) {
          await autoAct(); lastPress = Date.now();
        }
        prevY = h.y;
        await sleep(100);
      }
      if (curMin !== null && curMax - curMin > 100 && curMaxS > effA) effA = curMaxS;
      const elapsed = Math.max(1, (Date.now() - tStart) / 1000);
      const rate = scored > 0 ? scored / elapsed : 0;
      // Bar is >=1 flown, input-caused pipe (gap-blind autopilot + random gaps
      // make >=2 a lottery win, not a skill signal). The flight filter and the
      // hands-off ratio carry the anti-decoration load, not the count.
      C.scores = effA >= 1 && effA > 3 * scoreH && rate <= 2.0;
      if (!C.scores) out.notes.push(`score: auto=${scored} flown=${effA} handsOff=${scoreH} rate=${rate.toFixed(2)}/s over ${elapsed.toFixed(0)}s`);
      await endPhase(s);
      // ---- L4b: game over with no input, dying near the ground ----
      // (a no-input bird falls fast and dies on the floor ~1s in, long before
      // pipes arrive; death far from the ground = missing floor, Artemis-class)
      s = await freshPhase(html);
      const H4 = await s.page.evaluate(() => { const c = document.querySelector('canvas'); return c ? c.height : 600; });
      // Start the game, then hands off: an unplayed bird must fall and die
      // at the ground. (Pure no-input fails legit tap-to-start games whose
      // start screen waits forever — real Flappy does exactly that.)
      await s.page.keyboard.press('Space'); await sleep(200);
      {
        const bx4 = await (await s.page.$('canvas')).boundingBox();
        await s.page.mouse.click(bx4.x + bx4.width / 2, bx4.y + bx4.height / 2);
      }
      await sleep(300);
      let died = false, deathY = null;
      const tEnd2 = Date.now() + 30000;
      while (Date.now() < tEnd2) {
        const h = await readHooks(s.page);
        if (!h || h === 'eval-threw') break;
        if (!h.over) deathY = h.y;
        if (h.over) { died = true; break; }
        await sleep(200);
      }
      C.gameover = died && deathY !== null && deathY >= H4 - 150 && deathY <= H4 + 100;
      if (died && !C.gameover) out.notes.push(`gameover: died at y=${Math.round(deathY)} vs ground ~${H4} (no floor)`);
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
    // Hard caps: input-response and input-caused scoring are THE game. Without
    // them the file is a demo/animatic, and partial-credit sums (≈67 for
    // flap+scores both failing) lie about that. Caps keep the ranking honest.
    if (C.hooks && !C.flap && out.score > 35) {
      out.score = 35;
      out.notes.push('cap: no input response -> max 35 (decorative)');
    }
    if (C.hooks && C.flap && !C.scores && out.score > 50) {
      out.score = 50;
      out.notes.push('cap: nothing flown+scored -> max 50 (unplayable)');
    }
  } catch (e) {
    out.notes.push('GRADER-ERROR: ' + String(e).slice(0, 200));
  }
  out.ms = Date.now() - t0;
  console.log(JSON.stringify(out));
})();
