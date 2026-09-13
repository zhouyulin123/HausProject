/** 开发版浏览器验收：真实页面、真实 API；需要本机 Chrome、playwright 和 sharp。 */
const { chromium } = require('playwright');
const sharp = require('sharp');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const base = process.env.HAUS_BROWSER_BASE || 'http://127.0.0.1:8080';
  assert(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
  const output = path.resolve('outputs/v1-browser');
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const errors = [];
  const report = { origin: 'synthetic', checks: [] };
  let page;
  try {
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(30000);
    page.setDefaultNavigationTimeout(30000);
    page.on('pageerror', error => errors.push({ text: error.message, url: '' }));
    page.on('console', message => {
      if (message.type() === 'error') errors.push({ text: message.text(), url: message.location().url });
    });
    async function create(index) {
      console.log('建立项目', index);
      await page.goto(`${base}/design/new`);
      await page.getByRole('button', { name: '建立项目', exact: true }).nth(index).click();
      await page.waitForURL('**/workspace');
      await page.getByRole('button', { name: '发送', exact: true }).waitFor();
    }
    async function chat(message) {
      console.log('提交对话', page.url());
      await page.locator('textarea').first().fill(message);
      const pending = page.waitForResponse(response => response.url().endsWith('/agent-turns')
        && response.request().method() === 'POST', { timeout: 180000 });
      await page.getByRole('button', { name: '发送', exact: true }).click();
      const response = await pending;
      assert.equal(response.status(), 200);
      return response.json();
    }
    async function capture(name, width, height) {
      console.log('截图', name);
      await page.setViewportSize({ width, height });
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
        `${name}: 页面横向溢出`);
    }
    await create(0);
    const facts = await chat('设计客厅，预算最多一万八千元，宽430厘米，层高2.7米，现代简约，房间长度和配送地区还没确定。');
    assert.equal(facts.status, 'waiting_user');
    assert.equal(facts.state.facts.budget_max, 18000);
    assert.equal(facts.state.facts.room_width_m, 4.3);
    const workspace = page.url();
    await page.reload();
    await page.getByRole('button', { name: '发送', exact: true }).waitFor();
    await page.getByText('正在连接智能体', { exact: false }).waitFor({ state: 'hidden' });
    await capture('chat-desktop', 1440, 1000);
    await capture('chat-mobile', 390, 844);
    report.checks.push({ name: '聊天需求与刷新恢复', workspace, facts: facts.state.facts });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await create(1);
    const geometry = await chat('设计一张圆形边几，高500毫米，台面直径450毫米，用浅木色台面和黑色圆柱底座。');
    assert.equal(geometry.status, 'completed');
    await page.locator('canvas').first().waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('canvas')].some(c => c.width > 100));
    await capture('geometry-desktop', 1440, 1000);
    const canvases = page.locator('canvas');
    const pixels = [];
    for (let index = 0; index < await canvases.count(); index++) {
      const canvas = canvases.nth(index);
      if (!await canvas.isVisible()) continue;
      const before = await canvas.screenshot();
      const stats = await sharp(before).stats();
      assert(stats.channels.slice(0, 3).some(c => c.stdev > 5), '3D 画面为空');
      const bounds = await canvas.boundingBox();
      await page.mouse.move(bounds.x + bounds.width * .5, bounds.y + bounds.height * .5);
      await page.mouse.down();
      await page.mouse.move(bounds.x + bounds.width * .65, bounds.y + bounds.height * .6, { steps: 12 });
      await page.mouse.up();
      const after = await canvas.screenshot();
      assert(!before.equals(after), '拖拽后画面没有变化');
      pixels.push({ width: bounds.width, height: bounds.height,
        deviation: stats.channels.slice(0, 3).map(c => c.stdev), rotation: true });
    }
    assert(pixels.length > 0);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: '3D', exact: true }).click();
    await capture('geometry-mobile', 390, 844);
    const mobileCanvas = page.locator('canvas').first();
    const mobileStats = await sharp(await mobileCanvas.screenshot()).stats();
    assert(mobileStats.channels.slice(0, 3).some(c => c.stdev > 5), '手机 3D 画面为空');
    report.checks.push({ name: '家具建模与画布', workspace: page.url(), pixels });
    // 匿名会话探测登录态时 /auth/me 返回 401 属于接口契约，不忽略其他 401。
    const expected = errors.filter(error => error.url === `${base}/api/auth/me`
      && error.text.includes('401 (Unauthorized)'));
    const unexpected = errors.filter(error => !expected.includes(error));
    assert.deepEqual(unexpected, [], '浏览器非预期控制台错误');
    report.expectedAnonymousAuthProbes = expected.length;
    report.consoleErrors = unexpected;
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    if (page) {
      console.error('失败页面', page.url(), await page.locator('body').innerText());
      await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    }
    throw error;
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
