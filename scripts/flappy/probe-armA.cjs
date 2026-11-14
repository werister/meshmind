// Probe [DBG-flap1]: Arm-A-only telemetry on ref-good — per-life death stats.
// Discriminates H1 (gap lottery) vs H3 (over-press/ceiling) vs H2 (startSeq).
const { chromium } = require('playwright');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const FILE = process.argv[2] || 'ref-good.html';
const RUNS = parseInt(process.argv[3] || '3', 10);
(async () => {
  try {
    for (let run = 0; run < RUNS; run++) {
      // one browser per run: single-process shell dies when its last page closes
      const browser = await chromium.launch({ args: ['--single-process', '--no-zygote', '--disable-gpu'] });
      const page = await browser.newPage({ viewport: { width: 500, height: 700 } });
      const errs = [];
      page.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
      await page.goto('file:///tmp/flappy-harness/' + FILE);
      await sleep(400);
      const H = await page.evaluate(() => { const c = document.querySelector('canvas'); return c ? c.height : 600; });
      const box = await (await page.$('canvas')).boundingBox();
      const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
      const read = () => page.evaluate(() => window.__flappy).catch(() => 'eval-threw');
      await page.keyboard.press('Space'); await sleep(200);
      await page.mouse.click(cx, cy); await sleep(300);
      const lives = [];
      let cur = null;
      const tEnd = Date.now() + 30000;
      let prevY = null, lastPress = 0;
      while (Date.now() < tEnd) {
        const h = await read();
        if (!h || h === 'eval-threw') break;
        if (h.over) {
          if (cur) { cur.deathY = cur.lastY; cur.score = h.score; lives.push(cur); cur = null; }
          await page.mouse.click(cx, cy); await sleep(250);
          await page.keyboard.press('r'); await sleep(250);
          await page.keyboard.press('Space'); await sleep(250);
          prevY = null;
          continue;
        }
        if (!cur) cur = { minY: h.y, maxY: h.y, frames: 0, lastY: h.y, score: 0 };
        cur.minY = Math.min(cur.minY, h.y); cur.maxY = Math.max(cur.maxY, h.y);
        cur.lastY = h.y; cur.frames++; cur.score = h.score;
        const dy = prevY === null ? 0 : h.y - prevY;
        // [DBG-flap1] candidate law: press only when FALLING below hover line.
        if (dy > 0 && h.y > H * 0.45 && Date.now() - lastPress > 180) {
          await page.keyboard.press('Space'); lastPress = Date.now();
        }
        prevY = h.y;
        await sleep(100);
      }
      if (cur) { lives.push(cur); }
      const maxS = Math.max(0, ...lives.map((l) => l.score));
      console.log(`[DBG-flap1] run${run} lives=${lives.length} maxScore=${maxS} H=${H} errs=${errs.length}`);
      for (const l of lives.slice(0, 12)) {
        const cause = l.deathY === undefined ? 'alive@30s' : (l.deathY >= H - 60 ? 'floor' : (l.deathY <= 60 ? 'ceiling' : 'pipe?'));
        console.log(`[DBG-flap1]   life frames=${l.frames} yRange=[${Math.round(l.minY)},${Math.round(l.maxY)}] deathY=${l.deathY === undefined ? '-' : Math.round(l.deathY)} score=${l.score} cause=${cause}`);
      }
      try { await browser.close(); } catch { /* already dead */ }
    }
  } finally { /* per-run browsers closed above */ }
})();
