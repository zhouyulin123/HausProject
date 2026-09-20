/** 家装工作区：真实隔离 API 保存、恢复与桌面/手机画布验收。 */
const {chromium}=require('playwright');
const sharp=require('sharp');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');

async function main(){
  const base=process.env.HAUS_BROWSER_BASE||'http://127.0.0.1:8085';
  const api=process.env.HAUS_SPATIAL_TEST_API||'http://127.0.0.1:8083';
  for(const url of [base,api])assert(['localhost','127.0.0.1'].includes(new URL(url).hostname));
  const output=path.resolve('outputs/v2-home-browser');await fs.mkdir(output,{recursive:true});
  const browser=await chromium.launch({channel:'chrome',headless:true});
  const report={backend:'isolated_sqlite_real_home_api',checks:[]};
  try{
    for(const width of [1440,390]){
      const fixture=await(await fetch(`${api}/fixture`,{method:'POST'})).json();
      const headers={'X-Session-ID':fixture.session_id,'Content-Type':'application/json'};
      const url=`${api}/api/design/tasks/${fixture.task_id}`;
      const space={schema_version:'spatial/1.0',unit:'m',scale_status:'confirmed',source_image_id:null,rooms:[{id:'r1',name:'客厅',height:2.8,polygon:[{x:0,z:0},{x:4,z:0},{x:4,z:3},{x:0,z:3}]}],walls:[],openings:[]};
      const seeded=await fetch(`${url}/space`,{method:'PUT',headers,body:JSON.stringify({base_version:0,client_mutation_id:`browser-${width}`,document:space})});assert.equal(seeded.status,200,await seeded.text());
      const context=await browser.newContext({viewport:{width,height:width===390?844:1000}});
      const page=await context.newPage(),errors=[];let failSave=false;
      page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
      await context.route(url=>url.pathname.startsWith('/api/'),async route=>{
        const target=new URL(route.request().url());
        if(/\/(space|home-design)(\/|$)/.test(target.pathname)){
          if(failSave&&route.request().method()==='PUT'){failSave=false;return route.fulfill({status:503,json:{detail:'验收网络中断'}});}
          return route.fulfill({response:await route.fetch({url:api+target.pathname+target.search})});
        }
        if(target.pathname.startsWith('/api/sessions'))return route.fulfill({json:{session_id:fixture.session_id}});
        if(target.pathname==='/api/auth/me')return route.fulfill({status:401,json:{detail:'未登录'}});
        if(target.pathname==='/api/shop')return route.fulfill({json:{shop_name:'Haus'}});
        return route.fulfill({status:404,json:{detail:'非本轮验收接口'}});
      });
      const tools=async()=>{if(width===390)await page.getByRole('button',{name:'编辑与清单',exact:true}).click();};
      const canvas=async()=>{if(width===390)await page.getByRole('button',{name:'当前方案',exact:true}).click();};
      try{
        await page.goto(`${base}/design/${fixture.task_id}/home-design`);
        await page.getByRole('heading',{name:'整屋家装设计',exact:true}).waitFor();
        await tools();await page.getByRole('button',{name:'添加概念物件',exact:true}).click();
        await page.getByLabel('名称',{exact:true}).fill('验收收纳柜');
        await page.getByRole('button',{name:'应用修改',exact:true}).click();
        failSave=true;await page.getByRole('button',{name:'保存草稿',exact:true}).click();
        await page.getByRole('button',{name:'重试保存',exact:true}).click();
        await page.getByText(/家装 V1/).waitFor();
        await page.reload();await page.getByText(/家装 V1/).waitFor();await tools();
        await page.getByRole('button',{name:/验收收纳柜/}).click();
        assert.equal(await page.getByLabel('名称',{exact:true}).inputValue(),'验收收纳柜');
        await page.getByLabel('宽（米）',{exact:true}).fill('1.5');await page.getByRole('button',{name:'应用修改',exact:true}).click();
        await page.getByRole('button',{name:'撤销',exact:true}).click();assert.equal(await page.getByLabel('宽（米）',{exact:true}).inputValue(),'1');
        await page.getByRole('button',{name:'重做',exact:true}).click();assert.equal(await page.getByLabel('宽（米）',{exact:true}).inputValue(),'1.5');
        await page.getByRole('button',{name:'表面材料',exact:true}).click();
        await page.getByLabel('材料名称',{exact:true}).fill('浅灰地砖');await page.getByRole('button',{name:'应用饰面',exact:true}).click();
        await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.getByText(/家装 V2/).waitFor();
        const saved=await(await fetch(`${url}/home-design`,{headers})).json();assert.equal(saved.document.objects[0].size.width,1.5);assert.equal(saved.document.surfaces[0].material.name,'浅灰地砖');assert.equal(saved.validation.valid,true);
        await page.getByRole('button',{name:'清单与比较',exact:true}).click();
        await page.getByText('总价：待报价',{exact:true}).waitFor();
        await page.getByRole('button',{name:'比较版本',exact:true}).click();
        await page.getByRole('heading',{name:'V1 → V2',exact:true}).waitFor();
        const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'下载此版本 JSON',exact:true}).click()]);
        const snapshot=JSON.parse(await fs.readFile(await download.path(),'utf8'));assert.equal(snapshot.home_version,2);assert.equal(snapshot.space_version,1);assert.equal(snapshot.total_price,null);assert.equal(snapshot.lines.find(x=>x.entity_type==='surface').quantity,12);
        if(process.env.HAUS_HOME_AGENT_STUB==='1'){
          await page.getByRole('button',{name:'AI 建议',exact:true}).click();
          await page.getByLabel('设计需求',{exact:true}).fill('调整当前收纳柜名称');
          await page.getByRole('button',{name:'获取建议',exact:true}).click();
          await page.getByRole('button',{name:'确认应用到草稿',exact:true}).waitFor();
          assert.equal((await(await fetch(`${url}/home-design`,{headers})).json()).version,2);
          await page.getByRole('button',{name:'确认应用到草稿',exact:true}).click();
          assert.equal((await(await fetch(`${url}/home-design`,{headers})).json()).version,2);
          await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.getByText(/家装 V3/).waitFor();
          assert.equal((await(await fetch(`${url}/home-design`,{headers})).json()).document.objects[0].name,'AI验收收纳柜');
          await page.reload();await page.getByText(/家装 V3/).waitFor();
          await page.getByRole('button',{name:'AI 建议',exact:true}).click();
          await page.getByRole('button',{name:'查看此轮建议',exact:true}).click();
          assert.equal(await page.getByRole('button',{name:'确认应用到草稿',exact:true}).isDisabled(),true);
          report.checks.push({width,agent:'stub_model_real_api',confirmBeforeSave:true,expiredProposalBlocked:true});
        }
        await canvas();await page.getByRole('button',{name:'3D',exact:true}).click();await page.locator('canvas').waitFor();
        await page.waitForTimeout(1200);
        const box=await page.locator('canvas').boundingBox();assert(box.width>200&&box.height>200);
        const before=await page.locator('canvas').screenshot();const stats=await sharp(before).stats();assert(stats.channels.slice(0,3).some(c=>c.stdev>5),'3D画布不可空白');
        await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.7,box.y+box.height*.6,{steps:12});await page.mouse.up();await page.waitForTimeout(400);
        assert(!before.equals(await page.locator('canvas').screenshot()),'拖动应改变视角');
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'页面不应横向溢出');
        await page.screenshot({path:path.join(output,`home-${width}.png`),fullPage:true});assert.deepEqual(errors,[]);
        report.checks.push({width,persistence:true,retry:true,undoRedo:true,surface:true,canvas:true,rotation:true});
      }catch(error){await page.screenshot({path:path.join(output,`failure-${width}.png`),fullPage:true});console.error(await page.locator('body').innerText(),errors);throw error;}finally{await context.close();}
    }
    await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
