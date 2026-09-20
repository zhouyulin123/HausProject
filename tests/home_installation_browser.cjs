/** 安装、点位与预留要求的隔离真实 API 浏览器验收。 */
const {chromium}=require('playwright');
const sharp=require('sharp');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');

async function main(){
  const base=process.env.HAUS_BROWSER_BASE||'http://127.0.0.1:8085';
  const api=process.env.HAUS_SPATIAL_TEST_API||'http://127.0.0.1:8083';
  for(const url of [base,api])assert(['127.0.0.1','localhost'].includes(new URL(url).hostname));
  const output=path.resolve('outputs/v2-home-installation');await fs.mkdir(output,{recursive:true});
  const browser=await chromium.launch({channel:'chrome',headless:true});const checks=[];
  try {for(const width of [1440,390]){
    const fixture=await(await fetch(`${api}/fixture`,{method:'POST'})).json();
    const headers={'X-Session-ID':fixture.session_id,'Content-Type':'application/json'};
    const root=`${api}/api/design/tasks/${fixture.task_id}`;
    const call=async(suffix,method='GET',body)=>{const r=await fetch(root+suffix,{method,headers,body:body?JSON.stringify(body):undefined});assert.equal(r.status,200,await r.clone().text());return r.json();};
    const space={schema_version:'spatial/1.0',unit:'m',scale_status:'confirmed',source_image_id:null,rooms:[{id:'r',name:'客厅',height:2.8,polygon:[{x:0,z:0},{x:6,z:0},{x:6,z:5},{x:0,z:5}]}],walls:[],openings:[]};
    await call('/space','PUT',{base_version:0,client_mutation_id:'space',document:space});
    const document={schema_version:'home-design/1.0',space_version:1,surfaces:[],objects:[{id:'desk',room_id:'r',name:'书桌',category:'furniture',position:{x:2,y:0,z:2},size:{width:1,height:0.8,depth:0.6},rotation:0,material:{name:'木色',color:'#b6a37f'}}]};
    await call('/home-design','PUT',{base_version:0,client_mutation_id:'home',document});
    const context=await browser.newContext({viewport:{width,height:width===390?844:1000}});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
    await context.route(url=>url.pathname.startsWith('/api/'),async route=>{
      const target=new URL(route.request().url());
      if(/\/(space|home-design)(\/|$)/.test(target.pathname))return route.fulfill({response:await route.fetch({url:api+target.pathname+target.search})});
      if(target.pathname.startsWith('/api/sessions'))return route.fulfill({json:{session_id:fixture.session_id}});
      if(target.pathname==='/api/auth/me')return route.fulfill({status:401,json:{detail:'未登录'}});
      if(target.pathname==='/api/shop')return route.fulfill({json:{shop_name:'Haus'}});
      return route.fulfill({status:404,json:{detail:'非本轮接口'}});
    });
    const tools=async()=>{if(width===390)await page.getByRole('button',{name:'编辑与清单',exact:true}).click();};
    try{
      await page.goto(`${base}/design/${fixture.task_id}/home-design`);await page.getByText(/家装 V1/).waitFor();await tools();
      await page.getByRole('button',{name:'已有点位',exact:true}).click();await page.getByRole('button',{name:'添加已有点位'}).click();
      await page.getByLabel('点位名称',{exact:true}).fill('书桌插座');await page.getByRole('combobox',{name:'所在房间'}).selectOption('r');
      await page.getByLabel('全局 X（米）',{exact:true}).fill('2');await page.getByLabel('全局 Z（米）',{exact:true}).fill('2');await page.getByLabel('离地高度（米）',{exact:true}).fill('0.3');
      assert.equal(await page.getByRole('checkbox',{name:'已按现场资料核对'}).isChecked(),false);
      await page.getByRole('button',{name:'保存点位到草稿'}).click();await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.getByText(/家装 V2/).waitFor();
      const initial=await call('/home-design');assert(initial.validation.issues.some(i=>i.code==='point_unconfirmed'));assert.equal(initial.document.points[0].confirmed,false);
      await page.getByRole('checkbox',{name:'已按现场资料核对'}).check();await page.getByRole('button',{name:'保存点位到草稿'}).click();
      await page.getByRole('button',{name:'撤销',exact:true}).click();assert.equal(await page.getByRole('checkbox',{name:'已按现场资料核对'}).isChecked(),false);
      await page.getByRole('button',{name:'重做',exact:true}).click();await page.reload();await page.getByText(/家装 V2/).waitFor();await tools();
      await page.getByRole('button',{name:'已有点位',exact:true}).click();await page.getByRole('button',{name:'书桌插座 插座 · 已核对',exact:true}).click();assert.equal(await page.getByRole('checkbox',{name:'已按现场资料核对'}).isChecked(),true);
      await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.getByText(/家装 V3/).waitFor();assert.equal((await call('/home-design')).document.points[0].confirmed,true);
      await page.getByRole('button',{name:'物件',exact:true}).click();
      await page.getByRole('button',{name:/^书桌\s/}).click();
      await page.getByText('安装与使用约束',{exact:true}).click();
      await page.getByRole('combobox',{name:'安装方式'}).selectOption('floor');
      await page.getByRole('checkbox',{name:'设置使用预留空间'}).check();
      for(const [label,value] of [['前方','0.6'],['后方','0'],['左侧','0'],['右侧','0'],['上方','0.2']])await page.getByLabel(`${label}（米）`,{exact:true}).fill(value);
      await page.getByRole('checkbox',{name:'已核对使用要求'}).check();
      await page.getByRole('combobox',{name:'关联已有点位'}).selectOption(initial.document.points[0].id);
      await page.getByLabel('最大连接距离（米）',{exact:true}).fill('1');
      await page.getByRole('button',{name:'应用修改',exact:true}).click();
      await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.getByText(/家装 V4/).waitFor();
      const constrained=await call('/home-design');assert.equal(constrained.document.objects[0].clearance.front,0.6);assert.equal(constrained.document.objects[0].installation.kind,'floor');assert.equal(constrained.document.objects[0].point_requirement.point_id,initial.document.points[0].id);assert.equal(constrained.validation.valid,true);
      if(width===390)await page.getByRole('button',{name:'当前方案',exact:true}).click();
      await page.getByRole('button',{name:'3D',exact:true}).click();const canvas=page.locator('canvas');await canvas.waitFor();await page.waitForTimeout(1000);
      const before=await canvas.screenshot();assert((await sharp(before).stats()).channels.some(c=>c.stdev>5));
      const box=await canvas.boundingBox();await page.mouse.move(box.x+box.width*.4,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.6,box.y+box.height*.6,{steps:10});await page.mouse.up();await page.waitForTimeout(200);assert(!before.equals(await canvas.screenshot()));
      await page.screenshot({path:`${output}/installation-${width}.png`,fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);assert.deepEqual(errors,[]);
      checks.push({width,pointCreate:true,explicitConfirmation:true,undoRedo:true,refreshRecovery:true,installationAndClearance:true,pointBinding:true,canvas:true});
    }catch(error){await page.screenshot({path:`${output}/failure-${width}.png`,fullPage:true});console.error(await page.locator('body').innerText());throw error;}finally{await context.close();}
  }}finally{await browser.close();}
  await fs.writeFile(`${output}/report.json`,JSON.stringify({backend:'isolated_sqlite_real_api',checks},null,2));console.log(JSON.stringify(checks));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
