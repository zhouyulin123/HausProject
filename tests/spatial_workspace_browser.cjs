/** 整屋浏览器验收：空间请求使用真实后端及隔离数据库，其他应用上下文显式模拟。 */
const {chromium}=require('playwright');
const sharp=require('sharp');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');

async function main(){
  const base=process.env.HAUS_BROWSER_BASE||'http://127.0.0.1:8085';
  const api=process.env.HAUS_SPATIAL_TEST_API||'http://127.0.0.1:8083';
  for(const url of [base,api])assert(['127.0.0.1','localhost'].includes(new URL(url).hostname));
  const fixture=await (await fetch(`${api}/fixture`,{method:'POST'})).json();
  assert.equal((await fetch(`${api}/uploads/spatial-source.webp`)).status,404);
  assert.equal((await fetch(`${api}/api/upload/images/${fixture.image_id}/content`,{headers:{'X-Session-ID':fixture.stranger_session_id}})).status,404);
  const output=path.resolve('outputs/v2-spatial-browser');await fs.mkdir(output,{recursive:true});
  const browser=await chromium.launch({channel:'chrome',headless:true});
  const report={backend:'isolated_sqlite_real_spatial_api',checks:[]};
  try{
    for(const width of [1440,390]){
      const context=await browser.newContext({viewport:{width,height:width===390?844:1000}});
      const page=await context.newPage();const errors=[];const unknown=[];
      page.on('pageerror',e=>errors.push(e.message));page.on('dialog',dialog=>dialog.accept());
      let failSave=false;
      let checkpointImage=width===1440?fixture.image_id:fixture.alternate_image_id;
      await context.route(url=>url.pathname.startsWith('/uploads/'),async route=>route.fulfill({response:await route.fetch({url:api+new URL(route.request().url()).pathname})}));
      await context.route(url=>url.pathname.startsWith('/api/'),async route=>{
        const pathname=new URL(route.request().url()).pathname;
        if(pathname.includes('/space')||/^\/api\/upload\/images\/\d+\/content$/.test(pathname)){
          if(failSave&&route.request().method()==='PUT'){failSave=false;return route.fulfill({status:503,json:{detail:'验收网络中断'}});}
          return route.fulfill({response:await route.fetch({url:api+pathname+new URL(route.request().url()).search})});
        }
        let json;
        if(pathname.startsWith('/api/sessions'))json={session_id:fixture.session_id};
        else if(pathname==='/api/auth/me')return route.fulfill({status:401,json:{detail:'未登录'}});
        else if(pathname.endsWith('/agent-state'))json={task_id:fixture.task_id,room_source:{image_id:checkpointImage,image_url:'/uploads/spatial-source.webp',file_name:'演示空间.webp'}};
        else if(pathname==='/api/shop')json={shop_name:'豪斯',phone:null,wechat:null,address:null,slogan:null,logo_url:null};
        else {unknown.push(pathname);return route.fulfill({status:404,json:{detail:'未定义验收接口'}});}
        return route.fulfill({json});
      });
      const show=async name=>{if(width===390)await page.getByRole('navigation',{name:'整屋工作区'}).getByRole('button',{name,exact:true}).click();};
      try{
        await page.goto(`${base}/design/${fixture.task_id}/space`);
        await page.getByRole('heading',{name:/整屋户型/,level:1}).waitFor();
        if(width===1440){
          await show('房间');await page.getByLabel('新房间名称',{exact:true}).fill('客厅');
          await page.getByRole('button',{name:'建立房间',exact:true}).click();
          await page.getByText('原始资料',{exact:true}).click();
          await page.locator('section[aria-label="空间原图"] img').waitFor();
          const sourceImage=page.locator('section[aria-label="空间原图"] img');
          assert((await sourceImage.getAttribute('src')).startsWith('blob:'));
          await sourceImage.evaluate(image=>image.decode());
          const [enlarged]=await Promise.all([context.waitForEvent('page'),page.getByRole('link',{name:'查看原图：演示空间.webp'}).click()]);
          await enlarged.waitForLoadState();assert(enlarged.url().startsWith('blob:'));await enlarged.close();
          await page.getByLabel('底图覆盖宽度 (m)',{exact:true}).fill('8');
          await page.getByRole('button',{name:'设置描绘底图',exact:true}).click();
          await page.locator('svg[aria-label="整屋平面画布"] image').waitFor();
          await page.evaluate(()=>{const decode=HTMLImageElement.prototype.decode;HTMLImageElement.prototype.decode=function(){return decode.call(this).then(()=>new Promise(resolve=>{window.finishReference=()=>{HTMLImageElement.prototype.decode=decode;resolve();};}));};});
          await page.getByRole('button',{name:'设置描绘底图',exact:true}).click();
          await page.waitForFunction(()=>typeof window.finishReference==='function');
          await page.getByLabel('房间名称',{exact:true}).fill('校验客厅');
          await page.getByRole('button',{name:'应用房间属性',exact:true}).click();
          await page.evaluate(()=>window.finishReference());
          await page.getByRole('alert').filter({hasText:'读取期间草稿已变化'}).waitFor();
          await page.getByLabel('房间名称',{exact:true}).fill('客厅');
          await page.getByRole('button',{name:'应用房间属性',exact:true}).click();
          await show('属性');await page.getByRole('button',{name:'按轮廓建立墙体',exact:true}).click();
          await page.getByRole('button',{name:'添加门窗',exact:true}).click();
          await page.getByLabel('开口类型',{exact:true}).selectOption('window');
          await page.getByLabel('起点偏移 (m)',{exact:true}).fill('2');
          await page.getByLabel('开口宽 (m)',{exact:true}).fill('0.8');
          await page.getByLabel('开口高 (m)',{exact:true}).fill('1');
          await page.getByLabel('窗台高 (m)',{exact:true}).fill('1');
          await page.getByRole('button',{name:'添加门窗',exact:true}).click();
          await page.getByLabel('已核对实际尺寸').check();
          await page.getByRole('button',{name:'保存',exact:true}).click();
          await page.getByRole('status').filter({hasText:/已保存 · V1/}).waitFor();
          await show('房间');await page.getByText('添加房间',{exact:true}).click();
          await page.getByLabel('新房间名称',{exact:true}).fill('卧室');
          await page.getByLabel('起点 X (m)',{exact:true}).fill('4');
          await page.getByRole('button',{name:'建立房间',exact:true}).click();
          await show('属性');await page.getByRole('button',{name:'按轮廓建立墙体',exact:true}).click();
          await page.getByLabel('已核对实际尺寸').check();
          failSave=true;await page.getByRole('button',{name:'保存',exact:true}).click();
          await page.getByRole('alert').filter({hasText:'验收网络中断'}).waitFor();
          await page.getByRole('button',{name:'重试保存',exact:true}).click();
          await page.getByRole('status').filter({hasText:/已保存 · V2/}).waitFor();
          const saved=await (await fetch(`${api}/api/design/tasks/${fixture.task_id}/space`,{headers:{'X-Session-ID':fixture.session_id}})).json();
          assert.equal(saved.document.rooms.length,2);assert.equal(saved.document.walls.length,7);assert.equal(saved.document.openings.length,2);assert.equal(saved.document.image_reference.width,8);
          await page.reload();await page.getByRole('status').filter({hasText:/已保存 · V2/}).waitFor();
          await page.getByRole('button',{name:/卧室.*m²/}).click();
          await page.getByLabel('房间名称',{exact:true}).fill('本地卧室');
          await page.getByRole('button',{name:'应用房间属性',exact:true}).click();
          const concurrent=structuredClone(saved.document);concurrent.rooms[1].name='远端卧室';
          concurrent.source_image_id=fixture.alternate_image_id;checkpointImage=fixture.alternate_image_id;
          const updated=await fetch(`${api}/api/design/tasks/${fixture.task_id}/space`,{method:'PUT',headers:{'X-Session-ID':fixture.session_id,'Content-Type':'application/json'},body:JSON.stringify({base_version:2,client_mutation_id:'external-edit',document:concurrent})});assert.equal(updated.status,200);
          await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('alert').filter({hasText:'草稿已保留'}).waitFor();
          await page.reload();await page.getByRole('alert').filter({hasText:'本机草稿已保留'}).waitFor();
          await page.getByRole('button',{name:'重新载入',exact:true}).first().click();
          await page.getByRole('status').filter({hasText:/已保存 · V3/}).waitFor();
          await page.getByText('版本历史',{exact:true}).click();await page.getByRole('button',{name:/V1 · 1 间/}).click();
          await page.locator('svg[aria-label="整屋平面画布"] image').waitFor();
          assert.equal(await page.getByText('该草稿关联的原图尚未恢复',{exact:true}).count(),0);
          await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('status').filter({hasText:/已保存 · V4/}).waitFor();
          await page.getByRole('button',{name:'描绘房间轮廓',exact:true}).click();
          for(const [x,z] of [[4.5,0],[7.5,0],[7.5,1],[5.5,1],[5.5,3],[4.5,3]]){
            const point=await page.locator('svg[aria-label="整屋平面画布"]').evaluate((svg,p)=>{const t=new DOMPoint(p[0],p[1]).matrixTransform(svg.getScreenCTM());return {x:t.x,y:t.y};},[x,z]);await page.mouse.click(point.x,point.y);
          }
          await page.getByRole('button',{name:'完成轮廓',exact:true}).click();
          await page.getByLabel('房间名称',{exact:true}).fill('L形书房');await page.getByRole('button',{name:'应用房间属性',exact:true}).click();
          await page.getByRole('button',{name:'按轮廓建立墙体',exact:true}).click();await page.getByLabel('已核对实际尺寸').check();
          await page.getByLabel('墙段高度 (m)',{exact:true}).fill('1.2');await page.getByRole('button',{name:'应用墙体属性',exact:true}).click();
          await page.getByRole('button',{name:'应用房间属性',exact:true}).click();
          assert.equal(await page.getByLabel('墙段高度 (m)',{exact:true}).inputValue(),'1.2');
          await page.getByLabel('已核对实际尺寸').check();
          await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('status').filter({hasText:/已保存 · V5/}).waitFor();
        }else {await page.getByRole('status').filter({hasText:/已保存 · V5/}).waitFor();await show('房间');await page.getByRole('button',{name:/客厅.*m²/}).click();await show('属性');await page.getByLabel('房间名称',{exact:true}).fill('客厅移动端');await page.getByRole('button',{name:'应用房间属性',exact:true}).click();await page.getByRole('button',{name:'撤销',exact:true}).click();await show('画布');}
        if(width===390){
          await show('房间');await page.getByText('原始资料',{exact:true}).click();
          const sourceImage=page.locator('section[aria-label="空间原图"] img');await sourceImage.waitFor();
          assert((await sourceImage.getAttribute('src')).startsWith('blob:'));await sourceImage.evaluate(image=>image.decode());
          const [enlarged]=await Promise.all([context.waitForEvent('page'),page.getByRole('link',{name:/查看原图：/}).click()]);
          await enlarged.waitForLoadState();assert(enlarged.url().startsWith('blob:'));await enlarged.close();
          await page.screenshot({path:`${output}/private-source-${width}.png`,fullPage:true});
        }
        await show('画布');
        assert((await page.locator('svg[aria-label="整屋平面画布"] image').getAttribute('href')).startsWith('blob:'));
        await page.screenshot({path:`${output}/plan-${width}.png`,fullPage:true});
        await page.getByRole('button',{name:'3D',exact:true}).click();const canvas=page.locator('canvas');await canvas.waitFor();await page.waitForTimeout(1200);
        const before=await canvas.screenshot();const stats=await sharp(before).stats();assert(stats.channels.some(c=>c.stdev>12),'三维画布必须包含实际几何');
        const box=await canvas.boundingBox();await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.7,box.y+box.height*.55,{steps:15});await page.mouse.up();await page.waitForTimeout(400);
        const after=await canvas.screenshot();assert(!before.equals(after),'三维拖动必须改变画布');
        await page.screenshot({path:`${output}/scene-${width}.png`,fullPage:true});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'页面横向溢出');
        assert.deepEqual(errors,[]);assert.deepEqual(unknown,[]);
        report.checks.push({width,realSave:true,recovery:true,privateImageBlob:true,staticDenied:true,foreignSessionDenied:true,canvasNonblank:true,canvasRotation:true,noOverflow:true});
      }catch(error){await page.screenshot({path:`${output}/failure-${width}.png`,fullPage:true});console.error({errors,unknown,body:await page.locator('body').innerText()});throw error;}finally{await context.close();}
    }
    await fs.writeFile(`${output}/report.json`,JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
