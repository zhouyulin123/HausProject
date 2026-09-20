/** D02 跨领域 AI 家具建议、预算证据及用户确认的隔离真实 API 验收。 */
const {chromium}=require('playwright');
const sharp=require('sharp');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');

async function main(){
  const base=process.env.HAUS_BROWSER_BASE||'http://127.0.0.1:8085';
  const api=process.env.HAUS_SPATIAL_TEST_API||'http://127.0.0.1:8083';
  for(const url of [base,api])assert(['127.0.0.1','localhost'].includes(new URL(url).hostname));
  const output=path.resolve('outputs/v2-home-agent-d02');await fs.mkdir(output,{recursive:true});
  const browser=await chromium.launch({channel:'chrome',headless:true});const checks=[];
  try{for(const width of [1440,390]){
    const fixture=await(await fetch(`${api}/fixture`,{method:'POST'})).json();
    const headers={'X-Session-ID':fixture.session_id,'Content-Type':'application/json'};
    const root=`${api}/api/design/tasks/${fixture.task_id}`;
    const call=async(suffix,method='GET',body)=>{const response=await fetch(root+suffix,{method,headers,body:body?JSON.stringify(body):undefined});assert.equal(response.status,200,await response.clone().text());return response.json();};
    const space={schema_version:'spatial/1.0',unit:'m',scale_status:'confirmed',source_image_id:null,rooms:[{id:'living',name:'客厅',height:2.8,polygon:[{x:0,z:0},{x:6,z:0},{x:6,z:5},{x:0,z:5}]}],walls:[],openings:[]};
    await call('/space','PUT',{base_version:0,client_mutation_id:'d02-space',document:space});
    const document={schema_version:'home-design/1.0',space_version:1,surfaces:[],objects:[]};
    await call('/home-design','PUT',{base_version:0,client_mutation_id:'d02-home',document});
    const context=await browser.newContext({viewport:{width,height:width===390?844:1000}});const page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept());
    let assetGets=0;
    await context.route(url=>url.pathname.startsWith('/api/'),async route=>{
      const target=new URL(route.request().url());
      if(/\/home-design\/assets\/\d+$/.test(target.pathname)&&route.request().method()==='GET')assetGets++;
      if(/\/(space|home-design)(\/|$)/.test(target.pathname))return route.fulfill({response:await route.fetch({url:api+target.pathname+target.search})});
      if(target.pathname.startsWith('/api/sessions'))return route.fulfill({json:{session_id:fixture.session_id}});
      if(target.pathname==='/api/auth/me')return route.fulfill({status:401,json:{detail:'未登录'}});
      if(target.pathname==='/api/shop')return route.fulfill({json:{shop_name:'Haus'}});
      return route.fulfill({status:404,json:{detail:'非本轮接口'}});
    });
    const openTools=async()=>{if(width===390)await page.getByRole('button',{name:'编辑与清单',exact:true}).click();};
    const openAgent=async()=>{await openTools();await page.getByRole('button',{name:'AI 建议',exact:true}).click();};
    try{
      await page.goto(`${base}/design/${fixture.task_id}/home-design`);await page.getByText(/家装 V1/).waitFor();
      assert.equal(assetGets,0,'2D 初始视图不应读取家具模型');
      await openAgent();
      await page.getByRole('button',{name:/验收商业休闲椅/}).click();
      await page.getByRole('button',{name:/允许 AI 使用“验收商业休闲椅”/}).click();
      await page.getByLabel('AI 交付地区').fill('CN-SH');await page.getByLabel('AI 本轮预算上限').fill('1000');
      await page.getByLabel('设计需求').fill('在客厅加入一把我授权的休闲椅，保留来源并检查预算。');
      await page.getByRole('button',{name:'获取建议',exact:true}).click();
      await page.getByText('在本轮预算内',{exact:true}).waitFor();
      assert.equal(await page.getByText('已知小计：680 CNY',{exact:true}).count(),1);
      assert.equal((await call('/home-design')).version,1,'建议生成不得自动保存');
      await page.getByRole('button',{name:'确认应用到草稿',exact:true}).click();
      assert.equal((await call('/home-design')).version,1,'应用候选只进入本机草稿');
      if(width===390)await page.getByRole('button',{name:'编辑与清单',exact:true}).click();
      await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.getByText(/家装 V2/).waitFor();
      const saved=await call('/home-design');assert.equal(saved.document.objects[0].asset_id>0,true);assert.equal(saved.document.objects[0].name,'验收商业休闲椅');

      await openAgent();await page.getByLabel('AI 本轮预算上限').fill('500');await page.getByLabel('设计需求').fill('再加入一把同款休闲椅，但不要超过本轮预算。');
      await page.getByRole('button',{name:'获取建议',exact:true}).click();await page.getByText('超出本轮预算',{exact:true}).waitFor();
      const apply=page.getByRole('button',{name:'确认应用到草稿',exact:true});assert.equal(await apply.isDisabled(),true);await page.getByText('候选已超出本轮预算，请调整预算或设计要求',{exact:true}).waitFor();
      assert.equal((await call('/home-design')).version,2,'超预算候选不能写入设计');

      if(width===390)await page.getByRole('button',{name:'当前方案',exact:true}).click();
      await page.getByRole('button',{name:'3D',exact:true}).click();const canvas=page.locator('canvas');await canvas.waitFor();await page.waitForTimeout(900);assert(assetGets>0,'切换 3D 后应按需读取家具模型');
      const before=await canvas.screenshot();assert((await sharp(before).stats()).channels.some(channel=>channel.stdev>5));const box=await canvas.boundingBox();await page.mouse.move(box.x+box.width*.4,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.65,box.y+box.height*.58,{steps:12});await page.mouse.up();await page.waitForTimeout(250);assert(!before.equals(await canvas.screenshot()));
      await page.screenshot({path:`${output}/d02-${width}.png`,fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);assert.deepEqual(errors,[]);
      checks.push({width,authorizedAsset:true,serverBudget:true,localCandidate:true,explicitSave:true,overBudgetBlocked:true,lazy3dAsset:true,canvas:true});
    }catch(error){await page.screenshot({path:`${output}/failure-${width}.png`,fullPage:true});console.error(await page.locator('body').innerText());throw error;}finally{await context.unrouteAll({behavior:'wait'});await context.close();}
  }}finally{await browser.close();}
  await fs.writeFile(`${output}/report.json`,JSON.stringify({backend:'isolated_sqlite_real_api',model:'explicit_controlled_stub',checks},null,2));console.log(JSON.stringify(checks));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
