/** C02：隔离真实 API 的家具入屋、恢复和模型画布验收。 */
const {chromium}=require('playwright');
const sharp=require('sharp');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');

async function main(){
  const base=process.env.HAUS_BROWSER_BASE||'http://127.0.0.1:8085';
  const api=process.env.HAUS_SPATIAL_TEST_API||'http://127.0.0.1:8083';
  for(const url of [base,api])assert(['127.0.0.1','localhost'].includes(new URL(url).hostname));
  const output=path.resolve('outputs/v2-home-assets');await fs.mkdir(output,{recursive:true});
  const browser=await chromium.launch({channel:'chrome',headless:true});
  const checks=[];
  try{
    for(const width of [1440,390]){
      const fixture=await(await fetch(`${api}/fixture`,{method:'POST'})).json();
      const headers={'X-Session-ID':fixture.session_id,'Content-Type':'application/json'};
      const url=`${api}/api/design/tasks/${fixture.task_id}`;
      const space={schema_version:'spatial/1.0',unit:'m',scale_status:'confirmed',source_image_id:null,
        rooms:[{id:'r1',name:'客厅',height:2.8,polygon:[{x:0,z:0},{x:6,z:0},{x:6,z:5},{x:0,z:5}]}],walls:[],openings:[]};
      const seeded=await fetch(`${url}/space`,{method:'PUT',headers,body:JSON.stringify({base_version:0,client_mutation_id:`asset-${width}`,document:space})});
      assert.equal(seeded.status,200,await seeded.text());
      const context=await browser.newContext({viewport:{width,height:width===390?844:1000}});
      const page=await context.newPage(),errors=[];let failAsset=false;
      page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
      await context.route(url=>url.pathname.startsWith('/api/'),async route=>{
        const target=new URL(route.request().url());
        if(/\/(space|home-design)(\/|$)/.test(target.pathname)){
          if(failAsset && /\/assets\/\d+$/.test(target.pathname)){failAsset=false;return route.fulfill({status:503,json:{detail:'验收临时断网'}});}
          return route.fulfill({response:await route.fetch({url:api+target.pathname+target.search})});
        }
        if(target.pathname.startsWith('/api/sessions'))return route.fulfill({json:{session_id:fixture.session_id}});
        if(target.pathname==='/api/auth/me')return route.fulfill({status:401,json:{detail:'未登录'}});
        if(target.pathname==='/api/shop')return route.fulfill({json:{shop_name:'Haus'}});
        return route.fulfill({status:404,json:{detail:'非本轮接口'}});
      });
      const tools=async()=>{if(width===390)await page.getByRole('button',{name:'编辑与清单',exact:true}).click();};
      const canvas=async()=>{if(width===390)await page.getByRole('button',{name:'当前方案',exact:true}).click();};
      try{
        await page.goto(`${base}/design/${fixture.task_id}/home-design`);
        await page.getByRole('heading',{name:'整屋家装设计',exact:true}).waitFor();
        await tools();await page.getByRole('button',{name:'家具库',exact:true}).click();
        await page.getByRole('button',{name:/验收样板休闲椅.*来源/}).click();
        const add=page.getByRole('button',{name:'加入客厅',exact:true});await add.waitFor();
        assert.equal((await(await fetch(`${url}/home-design`,{headers})).json()).version,0);
        await add.click();
        assert.equal(await page.getByLabel('宽（米）',{exact:true}).isEditable(),false);
        await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.getByText(/家装 V1/).waitFor();
        const saved=await(await fetch(`${url}/home-design`,{headers})).json();assert(saved.document.objects[0].asset_id);
        failAsset=true;await page.reload();await page.getByText(/家装 V1/).waitFor();
        await canvas();const failed=page.waitForResponse(response=>/\/home-design\/assets\/\d+$/.test(new URL(response.url()).pathname)&&response.status()===503);
        await page.getByRole('button',{name:'3D',exact:true}).click();await failed;await tools();
        await page.getByText('部分家具模型读取失败，显示占位线框',{exact:true}).waitFor();
        await page.getByRole('button',{name:'重试模型',exact:true}).click();
        await page.getByRole('button',{name:'家具库',exact:true}).click();
        await page.getByRole('button',{name:'本任务作品',exact:true}).click();
        await page.locator('.hd-asset-options > button').first().click();await add.click();
        await page.getByRole('button',{name:'撤销',exact:true}).click();
        await page.getByRole('button',{name:'重做',exact:true}).click();
        await page.getByLabel('全局 X（米）',{exact:true}).fill('1');
        await page.getByRole('button',{name:'应用修改',exact:true}).click();
        await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.getByText(/家装 V2/).waitFor();
        const latest=await(await fetch(`${url}/home-design`,{headers})).json();
        assert.equal(latest.document.objects.length,2);assert(latest.document.objects.every(o=>o.asset_id));
        const delivery=await(await fetch(`${url}/home-design/versions/2/delivery`,{headers})).json();
        assert.equal(delivery.assets.length,2);assert.equal(delivery.total_price,null);
        await canvas();await page.getByRole('button',{name:'3D',exact:true}).click();
        const view=page.locator('canvas');await view.waitFor();await page.waitForTimeout(1500);
        const before=await view.screenshot();const stats=await sharp(before).stats();assert(stats.channels.some(c=>c.stdev>5));
        const box=await view.boundingBox();await page.mouse.move(box.x+box.width*.45,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.65,box.y+box.height*.6,{steps:15});await page.mouse.up();await page.waitForTimeout(300);
        assert(!before.equals(await view.screenshot()));
        await page.screenshot({path:`${output}/assets-${width}.png`,fullPage:true});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);assert.deepEqual(errors,[]);
        checks.push({width,frozenAssets:2,explicitSave:true,reload:true,retry:true,undoRedo:true,canvas:true,rotation:true});
      }catch(e){await page.screenshot({path:`${output}/failure-${width}.png`,fullPage:true});console.error(await page.locator('body').innerText());throw e;}
      finally{await context.close();}
    }
    await fs.writeFile(`${output}/report.json`,JSON.stringify({backend:'isolated_sqlite_real_api',checks},null,2));console.log(JSON.stringify(checks));
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
