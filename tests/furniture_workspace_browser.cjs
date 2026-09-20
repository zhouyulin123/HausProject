/** 家具工作台布局验收：新建独立测试项目，不修改已有作品。 */
const { chromium } = require('playwright');
const sharp = require('sharp');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');

async function main() {
  const base = process.env.HAUS_BROWSER_BASE || 'http://127.0.0.1:8080';
  assert(['localhost', '127.0.0.1'].includes(new URL(base).hostname));
  const output = 'outputs/furniture-workspace';
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(`${base}/design/new`);
    await page.getByRole('button', { name: '开始设计家具', exact: true }).click();
    await page.waitForURL('**/workspace');
    await page.getByText('智能体已连接', { exact: false }).waitFor();
    assert.equal(await page.getByText('确认当前方案', { exact: true }).count(), 0);
    assert.equal(await page.getByText('降低预算', { exact: true }).count(), 0);
    await page.getByRole('button', { name: '调整尺寸', exact: true }).click();
    assert.equal(await page.getByRole('textbox', { name: '设计需求' }).inputValue(), '调整尺寸：');
    await page.getByRole('textbox', { name: '设计需求' }).fill('设计一张圆形边几，高500毫米，台面直径450毫米，浅木色台面和黑色圆柱底座。');
    const responsePromise = page.waitForResponse(r => r.url().endsWith('/agent-turns') && r.request().method() === 'POST', { timeout: 180000 });
    await page.getByRole('button', { name: '发送', exact: true }).click();
    const response = await responsePromise;
    assert.equal(response.status(), 200);
    const result = await response.json();
    assert(result.open_geometry?.current, '需要真实模型结果');
    await page.locator('canvas').waitFor();
    async function capture(name) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: `${output}/${name}.png`, fullPage: true });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '页面横向溢出');
    }
    async function checkCanvas() {
      const canvas = page.locator('canvas');
      let before;
      let stats;
      for (let attempt = 0; attempt < 30; attempt++) {
        before = await canvas.screenshot();
        stats = await sharp(before).stats();
        if (stats.channels.some(c => c.stdev > 5)) break;
        await page.waitForTimeout(100);
      }
      await fs.writeFile(`${output}/canvas.png`, before);
      await capture('latest');
      assert(stats.channels.some(c => c.stdev > 5), '画布为空');
      const box = await canvas.boundingBox();
      await page.mouse.move(box.x + box.width * .5, box.y + box.height * .5);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * .7, box.y + box.height * .6, { steps: 12 });
      await page.mouse.up();
      assert(!before.equals(await canvas.screenshot()), '画布不可旋转');
    }
    await checkCanvas();
    await capture('desktop');
    await page.getByRole('button', { name: '版本与放置', exact: true }).click();
    await page.getByText('尚未关联房间', { exact: true }).waitFor();
    assert.equal(await page.locator('#furniture-workspace-tools input[type=number]').count(), 0);
    await page.getByRole('button', { name: '收起工具', exact: true }).click();
    await page.getByRole('button', { name: '模板定制', exact: true }).click();
    const input = page.getByRole('textbox', { name: '草案名称', exact: true });
    await input.fill('布局验收草稿');
    await page.getByRole('button', { name: '收起工具', exact: true }).click();
    await page.getByRole('button', { name: '模板参数', exact: true }).click();
    assert.equal(await input.inputValue(), '布局验收草稿');
    await capture('template');
    await page.getByRole('button', { name: '对话作品', exact: true }).click();
    await page.getByRole('button', { name: '全屏查看', exact: true }).click();
    await capture('fullscreen');
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: '全屏查看', exact: true }).waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: '当前作品', exact: true }).click();
    await checkCanvas();
    assert((await page.locator('canvas').boundingBox()).height < 650, '手机画布高度不应继承桌面布局');
    await capture('mobile-model');
    await page.getByRole('button', { name: '对话', exact: true }).click();
    await capture('mobile-chat');
    await page.reload();
    await page.getByText('V1 · 已保存至服务端', { exact: true }).waitFor({ state: 'attached' });
    assert.deepEqual(errors, []);
    await fs.writeFile(`${output}/report.json`, JSON.stringify({ workspace: page.url(), errors, checks: ['真实生成', '双栏', '模板输入保留', '版本工具', '全屏与Escape', '桌面手机画布非空且可旋转', '刷新恢复'] }, null, 2));
    console.log('布局验收通过', page.url());
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
