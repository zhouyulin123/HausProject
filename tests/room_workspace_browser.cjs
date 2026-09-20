/** 工作台布局验收：真实入口，空间识别使用明确的测试响应，不调用付费模型。 */
const { chromium } = require('playwright');
const sharp = require('sharp');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
async function main() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const output = 'outputs/room-workspace';
  await fs.mkdir(output, { recursive: true });
  try {
    for (const entry of ['开始搭配', '开始设计房间']) {
      const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto('http://127.0.0.1:8080/design/new');
      await page.getByRole('button', { name: entry, exact: true }).click();
      await page.waitForURL('**/workspace');
      await page.getByRole('button', { name: '导入户型图或房间照片', exact: true }).waitFor();
      assert.equal(await page.getByRole('button', { name: '确认当前方案', exact: true }).count(), 0);
      await page.getByRole('button', { name: '预算明细', exact: true }).click();
      await page.getByText('生成正式方案后展示，不使用商品展示价推算', { exact: true }).waitFor();
      await page.getByRole('button', { name: '房间资料', exact: true }).click();
      await page.route('**/api/upload/image', route => route.fulfill({ json: {
        image_id: 999999, analysis: { findings: ['布局验收模拟识别'], room_model: {
          schemaVersion: '1.0', spaceType: '客厅', rooms: [{ id: 'room-test', name: '测试客厅', floorPolygon: [{x:0,z:0},{x:4,z:0},{x:4,z:5},{x:0,z:5}], ceilingHeight:2.8, confidence:0.8 }],
          walls: [], doors: [], windows: [], fixedObstacles: [], existingFurniture: [], scale:{source:'vl',confidence:0.8}, confidence:0.8,
          requiresConfirmation:['请确认房间实际尺寸'], analysisNotes:[], suggestions:[],
        } },
      } }));
      const image = await sharp({ create:{width:32,height:32,channels:3,background:'#ffffff'} }).png().toBuffer();
      await page.locator('input[type=file]').setInputFiles({ name:'layout-test.png', mimeType:'image/png', buffer:image });
      await page.getByText('请确认房间实际尺寸', { exact: true }).waitFor();
      await page.getByRole('button', { name:'收起工具', exact:true }).click();
      await page.locator('canvas').first().waitFor();
      for (const width of [1440,390]) {
        await page.setViewportSize({width,height:1000});
        if(width===390) await page.getByRole('button',{name:'当前方案',exact:true}).click();
        const canvas = page.locator('canvas').first();
        let before;
        for(let i=0;i<40;i++) {
          before=await canvas.screenshot();
          if((await sharp(before).stats()).channels.some(c=>c.stdev>5)) break;
          await page.waitForTimeout(100);
        }
        assert((await sharp(before).stats()).channels.some(c=>c.stdev>5));
        const box=await canvas.boundingBox();
        await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5);
        await page.mouse.down();
        await page.mouse.move(box.x+box.width*.7,box.y+box.height*.6,{steps:12});
        await page.mouse.up();
        assert(!before.equals(await canvas.screenshot()));
        await page.evaluate(()=>window.scrollTo(0,0));
        await page.screenshot({path:`${output}/${entry}-${width}.png`,fullPage:true});
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      }
      assert.deepEqual(errors,[]);
      console.log(entry, '布局、模拟上传、待确认、画布及移动端通过', page.url());
      await page.close();
    }
  } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
