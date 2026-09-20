/** C03：真实隔离 API 的户型影响、撤销、恢复和人工重新归属。 */
const {chromium}=require('playwright');
const sharp=require('sharp');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');

async function main(){
  const base=process.env.HAUS_BROWSER_BASE||'http://127.0.0.1:8085';
  const api=process.env.HAUS_SPATIAL_TEST_API||'http://127.0.0.1:8083';
  for(const url of [base,api])assert(['127.0.0.1','localhost'].includes(new URL(url).hostname));
  const output=path.resolve('outputs/v2-home-impact');await fs.mkdir(output,{recursive:true});
  const browser=await chromium.launch({channel:'chrome',headless:true});const checks=[];
  try{for(const width of [1440,390]){
    const fixture=await(await fetch(`${api}/fixture`,{method:'POST'})).json();
    const headers={'X-Session-ID':fixture.session_id,'Content-Type':'application/json'};
    const root=`${api}/api/design/tasks/${fixture.task_id}`;
    const call=async(suffix,method='GET',body)=>{
      const response=await fetch(root+suffix,{method,headers,body:body?JSON.stringify(body):undefined});
      assert.equal(response.status,200,await response.clone().text());return response.json();
    };
    const space={schema_version:'spatial/1.0',unit:'m',scale_status:'confirmed',source_image_id:null,
      rooms:[{id:'r1',name:'客厅',height:2.8,polygon:[{x:0,z:0},{x:6,z:0},{x:6,z:5},{x:0,z:5}]}],walls:[],openings:[]};
    await call('/space','PUT',{base_version:0,client_mutation_id:'space-1',document:space});
    const document={schema_version:'home-design/1.0',space_version:1,surfaces:[],objects:[{
      id:'desk',room_id:'r1',name:'书桌',category:'furniture',position:{x:4,y:0,z:2},
      size:{width:1,height:0.8,depth:0.6},rotation:0,material:{name:'木色',color:'#b6a37f'},
    }]};
    await call('/home-design','PUT',{base_version:0,client_mutation_id:'home-1',document});
    const oldDelivery=await call('/home-design/versions/1/delivery');
    const smaller=structuredClone(space);smaller.rooms[0].polygon=[{x:0,z:0},{x:3,z:0},{x:3,z:5},{x:0,z:5}];
    await call('/space','PUT',{base_version:1,client_mutation_id:'space-2',document:smaller});
    const context=await browser.newContext({viewport:{width,height:width===390?844:1000}});
    const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
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
      await page.goto(`${base}/design/${fixture.task_id}/home-design`);await page.getByText(/家装 V1/).waitFor();
      await tools();await page.getByRole('button',{name:'更新户型',exact:true}).click();
      await page.getByRole('button',{name:'检查最新户型',exact:true}).click();
      await page.getByText('书桌 超出房间边界',{exact:true}).waitFor();
      assert.equal((await call('/home-design')).document.space_version,1);
      await page.getByRole('button',{name:'载入新户型草稿',exact:true}).click();
      await page.getByText('当前绑定户型 V2',{exact:true}).waitFor();
      await page.getByRole('button',{name:'撤销',exact:true}).click();await page.getByText('当前绑定户型 V1',{exact:true}).waitFor();
      await page.getByRole('button',{name:'重做',exact:true}).click();await page.getByText('当前绑定户型 V2',{exact:true}).waitFor();
      await page.reload();await page.getByText(/家装 V1/).waitFor();await tools();
      await page.getByRole('button',{name:'更新户型',exact:true}).click();await page.getByText('当前绑定户型 V2',{exact:true}).waitFor();
      await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.getByText(/家装 V2/).waitFor();
      const updated=await call('/home-design');assert.equal(updated.document.space_version,2);assert.deepEqual(updated.document.objects,document.objects);
      assert.deepEqual(await call('/home-design/versions/1/delivery'),oldDelivery);
      const replaced=structuredClone(space);replaced.rooms[0].id='new-room';replaced.rooms[0].name='新客厅';
      await call('/space','PUT',{base_version:2,client_mutation_id:'space-3',document:replaced});
      await page.getByRole('button',{name:'检查最新户型',exact:true}).click();await page.getByRole('combobox',{name:/迁入房间/}).waitFor();
      assert.equal(await page.getByRole('button',{name:'载入新户型草稿',exact:true}).isDisabled(),true);
      await page.getByRole('combobox',{name:/迁入房间/}).selectOption('new-room');
      await page.getByRole('button',{name:'确认归属并重新检查',exact:true}).click();
      await page.getByRole('button',{name:'载入新户型草稿',exact:true}).click();
      await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.getByText(/家装 V3/).waitFor();
      assert.equal((await call('/home-design')).document.objects[0].room_id,'new-room');
      if(width===390)await page.getByRole('button',{name:'当前方案',exact:true}).click();
      await page.getByRole('button',{name:'3D',exact:true}).click();const canvas=page.locator('canvas');await canvas.waitFor();await page.waitForTimeout(1200);
      const before=await canvas.screenshot();assert((await sharp(before).stats()).channels.some(c=>c.stdev>5));
      const box=await canvas.boundingBox();await page.mouse.move(box.x+box.width*.4,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.6,box.y+box.height*.6,{steps:12});await page.mouse.up();await page.waitForTimeout(200);
      assert(!before.equals(await canvas.screenshot()));await page.screenshot({path:`${output}/impact-${width}.png`,fullPage:true});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);assert.deepEqual(errors,[]);
      checks.push({width,previewReadOnly:true,unchangedObjects:true,undoRedo:true,recovery:true,referenceRepair:true,historyImmutable:true,canvas:true});
    }catch(e){await page.screenshot({path:`${output}/failure-${width}.png`,fullPage:true});console.error(await page.locator('body').innerText());throw e;}
    finally{await context.close();}
  }}finally{await browser.close();}
  await fs.writeFile(`${output}/report.json`,JSON.stringify({backend:'isolated_sqlite_real_api',checks},null,2));console.log(JSON.stringify(checks));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
