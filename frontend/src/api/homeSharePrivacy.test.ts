import {readFileSync} from "node:fs";
import {it,expect} from "vitest";
it("分享入口在外部资源加载前禁止传递页面来源",()=>{
  const html=readFileSync(new URL("../../index.html",import.meta.url),"utf8");
  const policy='<meta name="referrer" content="no-referrer" />';
  expect(html).toContain(policy);
  expect(html.indexOf(policy)).toBeLessThan(html.indexOf('href="https://'));
});
