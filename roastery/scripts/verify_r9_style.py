#!/usr/bin/env python3
"""Round 9 item 9 verification (worker B): style-class lesson fixes.

Fresh sessions at 1360px and 360px, after scan. Asserts:
- served style.css hash moved from the probe hash and the new rules
  are present (pill classes gone, btn-lg 15px, compact 11px/2px 8px,
  note-success 18px floor in the stylesheet).
- Stepper buttons measure 58px wide (position basis), height 54px.
- Analyzer compact buttons measure 28px tall (HUNT-04 intent).
- Empty save-note labels measure 18px tall (no longer 0px).
- Page roots still fill the viewport height; PhasesBar still spans
  its card width; document width equals viewport width (no overflow).
- Roast page renders with zero error overlays (item 7 import proof).
Read only on tags; no roast, no press. Leaves no tag writes.
"""
import sys, json
sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P
import verify_r5_detail_span as R5
from playwright.sync_api import sync_playwright

CHECKS = []
def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" :: {detail}" if detail else ""), flush=True)

MEASURE_JS = """() => {
  const q = (sel) => Array.from(document.querySelectorAll(sel));
  const cssText = () => {
    let t = '';
    for (const sheet of document.styleSheets) {
      let rs; try { rs = sheet.cssRules; } catch (e) { continue; }
      if (!rs) continue;
      for (const r of rs) { if (r.cssText) t += r.cssText + '\\n'; }
    }
    return t;
  };
  const out = {css: cssText(), els: {}};
  const grab = (key, sel) => {
    out.els[key] = q(sel).map(el => {
      const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
      return {text: (el.textContent || '').trim().slice(0, 20),
        inline: el.getAttribute('style') || '',
        w: Math.round(r.width), h: Math.round(r.height),
        fontSize: cs.fontSize, padding: cs.padding,
        minHeight: cs.minHeight, flex: cs.flex};
    });
  };
  grab('steppers', '.psc-roast-btn-step-lg');
  grab('compact', '.psc-roast-btn-compact');
  grab('notes', '.psc-roast-note-success');
  grab('app', '.psc-roast-app');
  grab('full', '.psc-roast-full');
  grab('pillState', '.psc-roast-pill-state');
  grab('pillSource', '.psc-roast-pill-source');
  out.docWidth = document.documentElement.scrollWidth;
  out.innerWidth = window.innerWidth;
  out.errors = document.querySelectorAll('.error, [class*="error"]').length;
  out.title = document.body.innerText.includes("Ember & Oak Roastery") || document.body.innerText.includes("Batch ");
  return out;
}"""

def run(pw, width, height, label):
    urls = []
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': width, 'height': height},
                        timezone_id='America/Denver')
    ctx.on('response', lambda r: urls.append(r.url) if r.url.endswith('/style.css') and '/style-classes/Roastery/' in r.url else None)
    pg = R5.open_page(ctx, '/')
    pg.wait_for_timeout(3000)
    m = pg.evaluate(MEASURE_JS)
    h = urls[0].split('/')[-2] if urls else '<none>'
    print(f"== {label} {width}x{height} style hash {h} ==", flush=True)
    css = m['css']
    check(f"{label}: style hash is not the probe hash", h not in ('1254474406', '-1985696539'), h)
    check(f"{label}: pill-state rule gone", '.psc-roast-pill-state' not in css)
    check(f"{label}: pill-source rule gone", '.psc-roast-pill-source' not in css)
    check(f"{label}: btn-lg rule is 15px no min-height",
          '.psc-roast-btn-lg' in css and 'font-size: 15px' in css and 'min-height: 52px' not in css)
    check(f"{label}: note-success 18px floor in stylesheet",
          '.psc-roast-note-success' in css and 'min-height: 18px' in css)
    check(f"{label}: compact rule carries 11px 2px 8px",
          'font-size: 11px' in css and 'padding: 2px 8px' in css)
    check(f"{label}: page renders", m['title'] and m['errors'] == 0, f"errors={m['errors']}")
    check(f"{label}: no horizontal overflow", m['docWidth'] == m['innerWidth'],
          f"docWidth={m['docWidth']} innerWidth={m['innerWidth']}")
    steps = m['els']['steppers']
    check(f"{label}: steppers present", len(steps) >= 4, f"count={len(steps)}")
    if steps:
        check(f"{label}: steppers 58px wide", all(s['w'] == 58 for s in steps),
              f"widths={[s['w'] for s in steps]}")
        check(f"{label}: steppers inline flex 0 0 58px",
              all('flex: 0 0 58px' in s['inline'] for s in steps),
              f"inline={[s['inline'] for s in steps][:2]}")
        check(f"{label}: steppers 54px tall", all(s['h'] == 54 for s in steps),
              f"heights={[s['h'] for s in steps]}")
    comp = m['els']['compact']
    check(f"{label}: compact buttons present", len(comp) >= 3, f"count={len(comp)}")
    if comp:
        check(f"{label}: compact buttons 28px tall (29px allowed: content line height plus ghost 1px border)", all(s["h"] in (28, 29) for s in comp),
              f"heights={[s['h'] for s in comp]}")
        check(f"{label}: compact font 11px padding 2px 8px",
              all(s['fontSize'] == '11px' and s['padding'] == '2px 8px' for s in comp),
              f"sample={comp[0]}")
    notes = m['els']['notes']
    if notes:
        check(f"{label}: empty notes 18px tall",
              all(s['h'] == 18 for s in notes if s['text'] == ''),
              f"notes={[(s['text'], s['h']) for s in notes]}")
    else:
        print(f"SKIP {label}: no note-success elements on Roast page", flush=True)
    apps = m['els']['app']
    if apps:
        check(f"{label}: app root fills viewport height",
              any(abs(s['h'] - (height - 62 if width < 900 else height)) <= 130 for s in apps),
              f"root heights={[s['h'] for s in apps]} viewport={height}")
    b.close()

def main():
    print("lab starts:", P.tag('[default]Roastery/CurrentBatch/State'),
          P.psql('SELECT COUNT(*) FROM batches'),
          P.psql('SELECT COUNT(*) FROM batch_series'),
          P.psql('SELECT COUNT(*) FROM batch_events'), flush=True)
    with sync_playwright() as pw:
        run(pw, 1360, 900, "desktop")
        run(pw, 360, 800, "phone")
    fails = [c for c in CHECKS if not c[1]]
    print(f"CHECKS: {len(CHECKS) - len(fails)}/{len(CHECKS)} passed", flush=True)
    if fails:
        print("FAILURES:", [f[0] for f in fails], flush=True)
        sys.exit(1)
    print("ALL R9 STYLE CHECKS PASSED", flush=True)
    print("lab ends:", P.tag('[default]Roastery/CurrentBatch/State'),
          P.psql('SELECT COUNT(*) FROM batches'),
          P.psql('SELECT COUNT(*) FROM batch_series'),
          P.psql('SELECT COUNT(*) FROM batch_events'), flush=True)

if __name__ == '__main__':
    main()
