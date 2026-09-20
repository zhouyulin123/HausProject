/** 精确版本估价：真实 API、响应丢失恢复、未知价格不伪造。 */
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');

async function main(){
  const base=process.env.HAUS_BROWSER_BASE||'http://127.0.0.1:8085';
  const api=process.env.HAUS_SPATIAL_TEST_API||'http://127.0.0.1:8083';
  for(const url of [base,api])assert(['127.0.0.1','localhost'].includes(new URL(url).hostname));
  const output=path.resolve('outputs/v2-home-quotes');await fs.mkdir(output,{recursive:true});
  const browser=await chromium.launch({channel:'chrome',headless:true});const checks=[];
  try{for(const width of [1440,390]){
    const fixture=await(await fetch(`${api}/fixture`,{method:'POST'})).json();
    const headers={'X-Session-ID':fixture.session_id,'Content-Type':'application/json'};
    const root=`${api}/api/design/tasks/${fixture.task_id}`;
    const call=async(suffix,method='GET',body)=>{const r=await fetch(root+suffix,{method,headers,body:body?JSON.stringify(body):undefined});assert.equal(r.status,200,await r.clone().text());return r.json();};
    const space={schema_version:'spatial/1.0',unit:'m',scale_status:'confirmed',source_image_id:null,rooms:[{id:'r',name:'客厅',height:2.8,polygon:[{x:0,z:0},{x:6,z:0},{x:6,z:5},{x:0,z:5}]}],walls:[],openings:[]};
    await call('/space','PUT',{base_version:0,client_mutation_id:'space',document:space});
    const document={schema_version:'home-design/1.0',space_version:1,surfaces:[],objects:[{id:'desk',room_id:'r',name:'定制书桌',category:'furniture',position:{x:2,y:0,z:2},size:{width:1,height:0.8,depth:0.6},rotation:0,material:{name:'木色',color:'#b6a37f'}}]};
    await call('/home-design','PUT',{base_version:0,client_mutation_id:'home',document});
    const context=await browser.newContext({viewport:{width,height:width===390?844:1000}});const page=await context.newPage();const errors=[];let loseResponse=true;const payloads=[];page.on('pageerror',e=>errors.push(e.message));
    await context.route(url=>url.pathname.startsWith('/api/'),async route=>{
      const target=new URL(route.request().url());
      if(/\/(space|home-design)(\/|$)/.test(target.pathname)){
        const response=await route.fetch({url:api+target.pathname+target.search});
        if(target.pathname.endsWith('/quotes')&&route.request().method()==='POST'){
          payloads.push(route.request().postDataJSON());
          if(loseResponse){loseResponse=false;return route.fulfill({status:503,json:{detail:'验收：响应丢失'}});}
        }
        return route.fulfill({response});
      }
      if(target.pathname.startsWith('/api/sessions'))return route.fulfill({json:{session_id:fixture.session_id}});
      if(target.pathname==='/api/auth/me')return route.fulfill({status:401,json:{detail:'未登录'}});
      if(target.pathname==='/api/shop')return route.fulfill({json:{shop_name:'Haus'}});
      return route.fulfill({status:404,json:{detail:'非本轮接口'}});
    });
    const panel=async()=>{if(width===390)await page.getByRole('button',{name:'编辑与清单',exact:true}).click();await page.getByRole('button',{name:'清单与比较',exact:true}).click();};
    try{
      await page.goto(`${base}/design/${fixture.task_id}/home-design`);await page.getByText(/家装 V1/).waitFor();await panel();
      await page.getByLabel('估价地区代码',{exact:true}).fill('CN-SH');await page.getByRole('button',{name:'创建此版本估价',exact:true}).click();
      await page.getByRole('button',{name:'重试原估价请求',exact:true}).waitFor();await page.reload();await page.getByText(/家装 V1/).waitFor();await panel();
      const replay=page.waitForResponse(response=>new URL(response.url()).pathname.endsWith('/quotes')&&response.request().method()==='POST');
      await page.getByRole('button',{name:'重试原估价请求',exact:true}).click();assert.equal((await replay).status(),200);await page.getByText('待报价：1 项',{exact:true}).waitFor();
      assert.equal(payloads.length,2);assert.deepEqual(payloads[0],payloads[1]);
      const history=await call('/home-design/quotes?home_version=1');assert.equal(history.items.length,1);assert.equal(history.items[0].snapshot.total_price,null);
      await page.reload();await page.getByText(/家装 V1/).waitFor();await panel();await page.getByText('待报价：1 项',{exact:true}).waitFor();
      await page.screenshot({path:`${output}/quote-${width}.png`,fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);assert.deepEqual(errors,[]);
      checks.push({width,responseLost:true,reloadRetry:true,sameKey:true,oneSnapshot:true,unknownTotal:true,historyRecovery:true});
    }catch(error){await page.screenshot({path:`${output}/failure-${width}.png`,fullPage:true});console.error(await page.locator('body').innerText());throw error;}finally{await context.close();}
  }}finally{await browser.close();}
  await fs.writeFile(`${output}/report.json`,JSON.stringify({backend:'isolated_sqlite_real_api',checks},null,2));console.log(JSON.stringify(checks));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
