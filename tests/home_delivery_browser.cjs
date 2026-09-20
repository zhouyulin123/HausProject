/** 冻结交付、审阅、失联分享恢复、公开脱敏与撤销。 */
const {chromium}=require('playwright');
const sharp=require('sharp');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
async function main(){
 const base=process.env.HAUS_BROWSER_BASE||'http://127.0.0.1:8085',api=process.env.HAUS_SPATIAL_TEST_API||'http://127.0.0.1:8083';
 for(const url of [base,api])assert(['127.0.0.1','localhost'].includes(new URL(url).hostname));
 const output=path.resolve('outputs/v2-home-delivery');await fs.mkdir(output,{recursive:true});
 const browser=await chromium.launch({channel:'chrome',headless:true}),checks=[];
 try{for(const width of [1440,390]){
  const fixture=await(await fetch(`${api}/fixture`,{method:'POST'})).json(),headers={'X-Session-ID':fixture.session_id,'Content-Type':'application/json'},root=`${api}/api/design/tasks/${fixture.task_id}`;
  const call=async(suffix,method='GET',body)=>{const r=await fetch(root+suffix,{method,headers,body:body?JSON.stringify(body):undefined});assert.equal(r.status,200,await r.clone().text());return r.json();};
  const space={schema_version:'spatial/1.0',unit:'m',scale_status:'confirmed',source_image_id:fixture.image_id,rooms:[{id:'r',name:'客厅',height:2.8,polygon:[{x:0,z:0},{x:6,z:0},{x:6,z:5},{x:0,z:5}]},{id:'bed',name:'卧室',height:2.8,polygon:[{x:6,z:0},{x:10,z:0},{x:10,z:5},{x:6,z:5}]}],walls:[],openings:[]};
  await call('/space','PUT',{base_version:0,client_mutation_id:'space',document:space});
  const options=await call('/home-design/asset-options?kind=product');const source=options.items.find(i=>i.available);assert(source);
  const frozen=await call('/home-design/assets','POST',{client_mutation_id:'asset',kind:'product',source_id:source.source_id,source_version:source.source_version});
  const document={schema_version:'home-design/1.0',space_version:1,surfaces:[],objects:[{id:'chair',asset_id:frozen.id,room_id:'r',name:'阅读椅',category:'furniture',position:{x:2,y:0,z:2},size:frozen.size,rotation:0,material:frozen.material}]};
  await call('/home-design','PUT',{base_version:0,client_mutation_id:'home',document});
  const quote=await call('/home-design/quotes','POST',{home_version:1,region:'CN-SH',client_mutation_id:'quote'});
  for(let i=0;i<11;i++)await call('/home-design/quotes','POST',{home_version:1,region:'CN-SH',client_mutation_id:`older-selection-${i}`});
  const context=await browser.newContext({viewport:{width,height:width===390?844:1000}}),page=await context.newPage();const errors=[];let loseShare=true,corruptAsset=false;const sharePayloads=[];page.on('pageerror',e=>errors.push(e.message));
  await context.route(url=>url.pathname.startsWith('/api/'),async route=>{
   const target=new URL(route.request().url());
   if(target.pathname.startsWith('/api/home-shares/')){assert.equal(route.request().headers()['x-session-id'],undefined);assert.equal(route.request().headers().referer,undefined);return route.fulfill({response:await route.fetch({url:api+target.pathname})});}
   if(/\/(space|home-design)(\/|$)/.test(target.pathname)){
    const response=await route.fetch({url:api+target.pathname+target.search});
    if(corruptAsset&&/\/assets\/\d+$/.test(target.pathname)){corruptAsset=false;const value=await response.json();return route.fulfill({json:{...value,model_spec:{}}});}
    if(/\/deliveries\/\d+\/shares$/.test(target.pathname)&&route.request().method()==='POST'){sharePayloads.push(route.request().postDataJSON());if(loseShare){loseShare=false;return route.fulfill({status:503,json:{detail:'验收：分享响应丢失'}});}}
    return route.fulfill({response});
   }
   if(target.pathname.startsWith('/api/sessions'))return route.fulfill({json:{session_id:fixture.session_id}});
   if(target.pathname==='/api/auth/me')return route.fulfill({status:401,json:{detail:'未登录'}});
   if(target.pathname==='/api/shop')return route.fulfill({json:{shop_name:'Haus'}});
   return route.fulfill({status:404,json:{detail:'非本轮接口'}});
  });
  try{
   await page.goto(`${base}/design/${fixture.task_id}/home-design`);await page.getByText(/家装 V1/).waitFor();if(width===390)await page.getByRole('button',{name:'编辑与清单',exact:true}).click();
   await page.getByRole('button',{name:'清单与比较',exact:true}).click();await page.getByRole('button',{name:'加载更早估价',exact:true}).click();await page.getByRole('combobox',{name:'附带估价'}).selectOption(String(quote.id));
   await page.getByRole('button',{name:'冻结此版本交付',exact:true}).click();const entry=page.getByRole('link',{name:/查看交付 #/});await entry.waitFor();corruptAsset=true;await entry.click();await page.getByRole('heading',{name:'整屋设计方案',exact:true}).waitFor();
   await page.getByRole('button',{name:'3D',exact:true}).click();await page.getByRole('button',{name:'重试家具模型',exact:true}).waitFor();await page.getByRole('button',{name:'重试家具模型',exact:true}).click();await page.getByRole('button',{name:'重试家具模型',exact:true}).waitFor({state:'hidden'});await page.waitForTimeout(500);assert.equal(await page.getByRole('button',{name:'重试家具模型',exact:true}).count(),0);await page.getByRole('button',{name:'2D',exact:true}).click();
   assert(errors.length>0);assert(errors.every(message=>message==='冻结模型不支持确定性渲染'));errors.length=0;
   assert.equal(await page.getByRole('heading',{name:'客厅',exact:true}).count(),1);assert.equal(await page.getByRole('heading',{name:'卧室',exact:true}).count(),1);
   const deliveryId=Number(new URL(page.url()).pathname.split('/').at(-1));
   await page.getByLabel('审阅备注',{exact:true}).fill('请保留阅读角');await page.getByRole('button',{name:'记录审阅结果',exact:true}).click();await page.getByText(/已审阅 · .*请保留阅读角/).waitFor();
   await page.route('**/confirmations',route=>route.request().method()==='POST'?route.fulfill({status:409,json:{detail:'验收永久冲突'}}):route.fallback());
   await page.getByRole('button',{name:'记录审阅结果',exact:true}).click();await page.getByText(/confirmations -> 409/).waitFor();await page.reload();
   await page.getByRole('button',{name:'解除本机重试记录',exact:true}).waitFor();page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'解除本机重试记录',exact:true}).click();
   assert.equal(await page.getByRole('button',{name:'记录审阅结果',exact:true}).isEnabled(),true);await page.unroute('**/confirmations');
   await page.getByText(/材料清单及已附估价/).waitFor();
   await page.getByRole('checkbox').check();await page.getByRole('button',{name:'创建分享链接',exact:true}).click();await page.getByText(/shares -> 503/).waitFor();
   await page.reload();await page.getByRole('button',{name:'重试原操作',exact:true}).waitFor();const replay=page.waitForResponse(r=>/\/deliveries\/\d+\/shares$/.test(new URL(r.url()).pathname)&&r.request().method()==='POST');await page.getByRole('button',{name:'重试原操作',exact:true}).click();assert.equal((await replay).status(),200);
   await page.getByText('此分享已创建，但链接仅首次返回。可按记录撤销后重新创建。',{exact:true}).waitFor();assert.equal(sharePayloads.length,2);assert.deepEqual(sharePayloads[0],sharePayloads[1]);
   const oldShare=(await call('/home-design/shares')).items[0];await page.getByRole('button',{name:`撤销分享 #${oldShare.id}`,exact:true}).click();await page.getByText(new RegExp(`分享 #${oldShare.id}.*已撤销`)).waitFor();
   const createdResponse=page.waitForResponse(r=>/\/deliveries\/\d+\/shares$/.test(new URL(r.url()).pathname)&&r.request().method()==='POST');await page.getByRole('checkbox').check();await page.getByRole('button',{name:'创建分享链接',exact:true}).click();const createdShare=await(await createdResponse).json();const link=page.locator('a[href*="/home-share/"]');await link.waitFor();const shareUrl=await link.getAttribute('href');assert.equal(new URL(shareUrl).pathname,createdShare.share_url);
   const publicPage=await context.newPage();publicPage.on('pageerror',e=>errors.push(e.message));await publicPage.goto(shareUrl);await publicPage.getByRole('heading',{name:'整屋设计方案',exact:true}).waitFor();
   const token=new URL(shareUrl).pathname.split('/').at(-1);const publicValue=await(await fetch(`${api}/api/home-shares/${token}`)).json();
   assert.equal(publicValue.snapshot.document.objects[0].asset_id,undefined);assert.equal(publicValue.snapshot.space.source_image_id,undefined);assert.equal(publicValue.snapshot.assets,undefined);assert.equal(publicValue.snapshot.quote.total_price,null);
   await publicPage.getByRole('button',{name:'3D',exact:true}).click();const canvas=publicPage.locator('canvas');await canvas.waitFor();await publicPage.waitForTimeout(1000);assert((await sharp(await canvas.screenshot()).stats()).channels.some(c=>c.stdev>5));
   const rect=await canvas.boundingBox();assert(rect.height>300);const before=await canvas.screenshot();await publicPage.mouse.move(rect.x+rect.width*.5,rect.y+rect.height*.5);await publicPage.mouse.down();await publicPage.mouse.move(rect.x+rect.width*.7,rect.y+rect.height*.55,{steps:15});await publicPage.mouse.up();await publicPage.waitForTimeout(500);assert.notDeepEqual(await canvas.screenshot(),before);
   await publicPage.screenshot({path:`${output}/share-${width}.png`,fullPage:true});assert.equal(await publicPage.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await publicPage.emulateMedia({media:'print'});await publicPage.screenshot({path:`${output}/print-${width}.png`,fullPage:true});await publicPage.emulateMedia({media:'screen'});
   const latestShare=(await call('/home-design/shares')).items[0];assert.equal(latestShare.id,createdShare.id);const revokedResponse=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith(`/shares/${latestShare.id}/revoke`));await page.getByRole('button',{name:`撤销分享 #${latestShare.id}`,exact:true}).click();assert.equal((await revokedResponse).status(),200);await page.getByText(new RegExp(`分享 #${latestShare.id}.*已撤销`)).waitFor();assert.equal((await fetch(`${api}/api/home-shares/${token}`)).status,404);await publicPage.reload();await publicPage.getByRole('heading',{name:'分享链接不存在或已失效',exact:true}).waitFor().catch(async error=>{console.error('public page:',await publicPage.locator('body').innerText(),errors);throw error;});
   assert.equal((await call(`/home-design/deliveries/${deliveryId}/confirmations`)).items.length,1);assert.deepEqual(errors,[]);await publicPage.close();
   checks.push({width,freeze:true,quoteBinding:true,review:true,shareLostResponse:true,replayNoToken:true,publicProjection:true,print:true,canvas:true,renderFailureRetry:true,revoke:true});
  }catch(error){await page.screenshot({path:`${output}/failure-${width}.png`,fullPage:true});console.error(await page.locator('body').innerText());throw error;}finally{await context.close();}
 }}finally{await browser.close();}
 await fs.writeFile(`${output}/report.json`,JSON.stringify({backend:'isolated_sqlite_real_api',checks},null,2));console.log(JSON.stringify(checks));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
