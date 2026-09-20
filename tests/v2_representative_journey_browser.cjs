/** V2 开发代表案例：空间、材料、AI、估价、冻结交付与分享的同任务旅程。 */
const { chromium } = require("playwright");
const fs = require("node:fs/promises");
const path = require("node:path");
const assert = require("node:assert/strict");

async function main() {
  const base = process.env.HAUS_BROWSER_BASE || "http://127.0.0.1:8085";
  const api = process.env.HAUS_SPATIAL_TEST_API || "http://127.0.0.1:8083";
  const output = path.resolve("outputs/v2-representative-journey");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const checks = [];
  try {
    for (const width of [1440, 390]) {
      const fixture = await (await fetch(`${api}/fixture`, { method: "POST" })).json();
      const headers = { "X-Session-ID": fixture.session_id, "Content-Type": "application/json" };
      const root = `${api}/api/design/tasks/${fixture.task_id}`;
      const call = async (suffix, method = "GET", body) => {
        const response = await fetch(root + suffix, { method, headers, body: body ? JSON.stringify(body) : undefined });
        assert.equal(response.status, 200, await response.clone().text());
        return response.json();
      };
      const space = { schema_version: "spatial/1.0", unit: "m", scale_status: "confirmed", source_image_id: null, rooms: [{ id: "living", name: "客厅", height: 2.8, polygon: [{ x: 0, z: 0 }, { x: 6, z: 0 }, { x: 6, z: 5 }, { x: 0, z: 5 }] }], walls: [], openings: [] };
      await call("/space", "PUT", { base_version: 0, client_mutation_id: `journey-space-${width}`, document: space });
      await call("/home-design", "PUT", { base_version: 0, client_mutation_id: `journey-home-${width}`, document: { schema_version: "home-design/1.0", space_version: 1, surfaces: [], objects: [] } });

      const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 1000 } });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("dialog", (dialog) => dialog.accept());
      await context.route((url) => url.pathname.startsWith("/api/"), async (route) => {
        const target = new URL(route.request().url());
        if (target.pathname.startsWith("/api/design/tasks/") || target.pathname === "/api/products/quote-rules" || target.pathname.startsWith("/api/home-shares/")) {
          return route.fulfill({ response: await route.fetch({ url: api + target.pathname + target.search }) });
        }
        if (target.pathname.startsWith("/api/sessions")) return route.fulfill({ json: { session_id: fixture.session_id } });
        if (target.pathname === "/api/auth/me") return route.fulfill({ status: 401, json: { detail: "未登录" } });
        if (target.pathname === "/api/shop") return route.fulfill({ json: { shop_name: "Haus" } });
        return route.fulfill({ status: 404, json: { detail: "非本轮接口" } });
      });
      const tools = async () => {
        if (width === 390) await page.getByRole("button", { name: "编辑与清单", exact: true }).click();
      };
      try {
        await page.goto(`${base}/design/${fixture.task_id}/home-design`);
        await page.locator(".hd-header small").filter({ hasText: "家装 V1" }).waitFor();

        await tools();
        await page.getByRole("button", { name: "表面材料", exact: true }).click();
        await page.getByLabel("材料名称", { exact: true }).fill("耐磨地板");
        const ruleSelect = page.locator('select[name="quote_rule"]');
        const ruleId = await ruleSelect.locator("option").nth(1).getAttribute("value");
        await ruleSelect.selectOption(ruleId);
        await page.getByRole("button", { name: "应用饰面", exact: true }).click();
        await page.getByRole("button", { name: "保存草稿", exact: true }).click();
        await page.locator(".hd-header small").filter({ hasText: "家装 V2" }).waitFor();

        await tools();
        await page.getByRole("button", { name: "AI 建议", exact: true }).click();
        await page.getByRole("button", { name: /验收商业休闲椅/ }).click();
        await page.getByRole("button", { name: /允许 AI 使用“验收商业休闲椅”/ }).click();
        await page.getByLabel("AI 交付地区").fill("CN-SH");
        await page.getByLabel("AI 本轮预算上限").fill("5000");
        await page.getByLabel("设计需求").fill("在客厅加入授权休闲椅，保留地面材料并检查预算。");
        await page.getByRole("button", { name: "获取建议", exact: true }).click();
        await page.getByText("在本轮预算内", { exact: true }).waitFor();
        await page.getByText("已知小计：4,280 CNY", { exact: true }).waitFor();
        await page.getByRole("button", { name: "确认应用到草稿", exact: true }).click();
        if (width === 390) await page.getByRole("button", { name: "编辑与清单", exact: true }).click();
        await page.getByRole("button", { name: "保存草稿", exact: true }).click();
        await page.locator(".hd-header small").filter({ hasText: "家装 V3" }).waitFor();

        await tools();
        await page.getByRole("button", { name: "清单与比较", exact: true }).click();
        await page.getByLabel("估价地区代码", { exact: true }).fill("CN-SH");
        await page.getByRole("button", { name: "创建此版本估价", exact: true }).click();
        await page.getByText("待报价：0 项", { exact: true }).waitFor();
        await page.getByText(/当前清单合计：4,280\.00 CNY/).waitFor();
        const quote = (await call("/home-design/quotes?home_version=3")).items[0];
        await page.getByRole("button", { name: "刷新估价历史", exact: true }).last().click();
        await page.getByRole("combobox", { name: "附带估价" }).selectOption(String(quote.id));
        await page.getByRole("button", { name: "冻结此版本交付", exact: true }).click();
        const deliveryLink = page.getByRole("link", { name: /查看交付 #/ });
        await deliveryLink.waitFor();
        await deliveryLink.click();
        await page.getByRole("heading", { name: "整屋设计方案", exact: true }).waitFor();
        await page.getByText(/已知小计：4,280 元 · 待报价 0 项/).waitFor();
        await page.getByLabel(/我同意链接接收者查看/).check();
        const shared = page.waitForResponse((response) => /\/deliveries\/\d+\/shares$/.test(new URL(response.url()).pathname) && response.request().method() === "POST");
        await page.getByRole("button", { name: "创建分享链接", exact: true }).click();
        const share = await (await shared).json();
        const publicPage = await context.newPage();
        await publicPage.goto(new URL(share.share_url, base).href);
        await publicPage.getByRole("heading", { name: "整屋设计方案", exact: true }).waitFor();
        await publicPage.getByText(/当前清单合计：4,280 元/).waitFor();
        await publicPage.close();

        const finalDesign = await call("/home-design");
        assert.equal(finalDesign.version, 3);
        assert.equal(finalDesign.document.surfaces[0].quote_rule_id, Number(ruleId));
        assert.equal(finalDesign.document.objects[0].name, "验收商业休闲椅");
        assert.deepEqual(errors, []);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        await page.screenshot({ path: `${output}/journey-${width}.png`, fullPage: true });
        checks.push({ width, confirmedSpace: true, materialRule: true, controlledAI: true, explicitSave: true, total: 4280, frozenDelivery: true, controlledShare: true });
      } catch (error) {
        await page.screenshot({ path: `${output}/failure-${width}.png`, fullPage: true });
        console.error(await page.locator("body").innerText());
        throw error;
      } finally {
        await context.unrouteAll({ behavior: "wait" });
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
  await fs.writeFile(`${output}/report.json`, JSON.stringify({ backend: "isolated_sqlite_real_api", model: "controlled_stub_for_browser_only", checks }, null, 2));
  console.log(JSON.stringify(checks));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
