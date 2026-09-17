/** 原图恢复浏览器验收：隔离会话、模拟 API、仓库户型图，不调用模型或写业务库。 */
const { chromium } = require('playwright');
const sharp = require('sharp');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const base = process.env.HAUS_BROWSER_BASE || 'http://127.0.0.1:8082';
  assert(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
  const output = path.resolve('outputs/v2-room-source');
  await fs.mkdir(output, { recursive: true });
  const image = await fs.readFile(path.resolve('case_image/户型图1.png'));
  const model = {
    schemaVersion: '1.0', imageKind: 'floor_plan', spaceType: '客厅',
    rooms: [{ id: 'living', name: '客厅', confidence: 0.8, ceilingHeight: 2.8,
      widthM: 4.2, depthM: 5.5,
      floorPolygon: [{ x: 0, z: 0 }, { x: 1, z: 0 }, { x: 1, z: 1 }, { x: 0, z: 1 }] }],
    walls: [], doors: [], windows: [], fixedObstacles: [], existingFurniture: [],
    scale: { source: 'vl', confidence: 0.8 }, confidence: 0.8,
    requiresConfirmation: ['请核对空间尺寸'], analysisNotes: [], suggestions: [],
  };
  const checkpoint = {
    task_id: 42, state_version: 0, confirmed_requirement: {}, room_model: model,
    room_source: { image_id: 8, image_url: '/uploads/8-source.png', file_name: '户型原图.png' },
    status: 'draft', active_mode: 'room_reconstruction', active_room_id: 'living',
    intent: 'unknown', current_node: 'start', facts: {}, fact_evidence: {},
    pending_questions: [], step_count: 0, retry_count: 0, max_steps: 12, max_retries: 2,
    hard_errors: [], custom_furniture_spec: null, custom_furniture_draft: null,
    custom_furniture_draft_ref: null, approval_required: false, exit_reason: 'missing_facts',
    scene_ref: null, run_id: null, cost_cny: null, cost_reserved_cny: 0, cost_limit_cny: null,
    execution_deadline_at: null, cancel_requested_at: null, turn_execution_deadline_at: null,
    result: null, messages: [], open_geometry: null,
  };
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const report = { origin: 'synthetic', checks: [] };
  try {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 1000 } });
      const page = await context.newPage();
      const errors = [];
      const unexpected = [];
      page.on('pageerror', error => errors.push(error.message));
      let current = structuredClone(checkpoint);
      let brokenImage = false;
      await context.route('**/uploads/*', route => brokenImage
        ? route.fulfill({ status: 404, body: '' })
        : route.fulfill({ contentType: 'image/png', body: image }));
      await context.route(url => url.pathname.startsWith('/api/'), async route => {
        const pathname = new URL(route.request().url()).pathname;
        let json;
        if (pathname.startsWith('/api/sessions')) json = { session_id: 'browser-room-source-session' };
        else if (pathname === '/api/auth/me') return route.fulfill({ status: 401, json: { detail: '未登录' } });
        else if (pathname.endsWith('/agent-state')) json = current;
        else if (pathname.endsWith('/agent-events')) json = { events: [], has_more: false, next_before_id: null };
        else if (pathname.endsWith('/agent-approvals')) json = { approvals: [] };
        else if (pathname.endsWith('/timeline')) json = {
          task_id: 42, events: [], next_cursor: null, next_before_id: null, next_after_id: null,
          known_cost_cny: null, has_unknown_cost: false, unknown_cost_event_count: 0,
        };
        else if (pathname === '/api/shop') json = { shop_name: '豪斯', phone: null, wechat: null, address: null, slogan: null, logo_url: null };
        else if (pathname === '/api/products') json = { products: [{ id: 1, sku: 'TEST', name: '测试家具', price_text: '待报价', eligibility: { eligible: false, reason_codes: ['development_fixture'] } }] };
        else if (pathname === '/api/upload/image') {
          current = { ...current, room_source: { image_id: 9, image_url: '/uploads/9-source.png', file_name: '更新户型.png' } };
          json = { image_id: 9, image_url: '/uploads/9-source.png', analysis: { findings: [], source: 'vl', room_model: model } };
        } else {
          unexpected.push(pathname);
          return route.fulfill({ status: 404, json: { detail: '验收未定义接口' } });
        }
        return route.fulfill({ json });
      });
      async function showRoom() {
        try {
          if (width === 390) await page.getByRole('button', { name: '当前方案', exact: true }).click();
          await page.getByRole('button', { name: '房间资料', exact: true }).click();
        } catch (error) {
          await page.screenshot({ path: `${output}/failure-${width}.png`, fullPage: true });
          console.error({ body: await page.locator('body').innerText(), errors, unexpected });
          throw error;
        }
      }
      await page.goto(`${base}/design/42/workspace`);
      await showRoom();
      const original = page.getByRole('link', { name: '查看原图：户型原图.png', exact: true });
      await original.waitFor();
      await page.waitForFunction(() => {
        const img = document.querySelector('section[aria-label="空间原图"] img');
        return img?.complete && img.naturalWidth > 0;
      });
      assert.equal(await original.getAttribute('href'), '/uploads/8-source.png');
      assert(await page.evaluate(() => {
        const panel = document.getElementById('room-workspace-tools');
        const rect = panel.getBoundingClientRect();
        const labels = [...document.querySelectorAll('div, span')].filter(node =>
          node.children.length === 0 && /^\d+\.\d+ m$/.test(node.textContent.trim()));
        if (!labels.length) return false;
        return labels.every(label => {
          const box = label.getBoundingClientRect();
          const x = box.x + box.width / 2;
          const y = box.y + box.height / 2;
          if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom || y >= innerHeight) return true;
          return panel.contains(document.elementFromPoint(x, y));
        });
      }), '3D 尺寸标签不得遮挡房间资料工具');
      await page.screenshot({ path: `${output}/source-${width}.png`, fullPage: true });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));

      await page.locator('input[type=file]').setInputFiles({ name: '更新户型.png', mimeType: 'image/png', buffer: image });
      await page.getByRole('link', { name: '查看原图：更新户型.png', exact: true }).waitFor();
      await page.evaluate(() => localStorage.removeItem('ai-home-design-projects'));
      await page.reload();
      await showRoom();
      await page.getByRole('link', { name: '查看原图：更新户型.png', exact: true }).waitFor();
      await page.getByRole('button', { name: '收起工具', exact: true }).click();
      const canvas = page.locator('canvas').first();
      await canvas.waitFor();
      let pixels;
      for (let attempt = 0; attempt < 30; attempt++) {
        pixels = await canvas.screenshot();
        if ((await sharp(pixels).stats()).channels.some(channel => channel.stdev > 5)) break;
        await page.waitForTimeout(100);
      }
      assert((await sharp(pixels).stats()).channels.some(channel => channel.stdev > 5));
      const box = await canvas.boundingBox();
      await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.6, { steps: 10 });
      await page.mouse.up();
      assert(!pixels.equals(await canvas.screenshot()));
      await page.screenshot({ path: `${output}/scene-${width}.png`, fullPage: true });

      brokenImage = true;
      await page.reload();
      await showRoom();
      await page.getByText('原图暂不可用', { exact: true }).waitFor();
      assert.deepEqual(errors, []);
      assert.deepEqual(unexpected, []);
      report.checks.push({ width, coldRestore: true, upload: true, cacheLossRestore: true, imageFailure: true, canvasPixels: true, canvasRotation: true, overflow: false });
      await context.close();
    }
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
