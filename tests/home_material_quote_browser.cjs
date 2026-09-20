/** 表面材料规则绑定与确定性估价：桌面/手机真实 API 验收。 */
const { chromium } = require("playwright");
const fs = require("node:fs/promises");
const path = require("node:path");
const assert = require("node:assert/strict");

async function main() {
  const base = process.env.HAUS_BROWSER_BASE || "http://127.0.0.1:8085";
  const api = process.env.HAUS_SPATIAL_TEST_API || "http://127.0.0.1:8083";
  for (const url of [base, api]) {
    assert(["127.0.0.1", "localhost"].includes(new URL(url).hostname));
  }
  const output = path.resolve("outputs/v2-home-material-quotes");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const checks = [];
  try {
    for (const width of [1440, 390]) {
      const fixture = await (await fetch(`${api}/fixture`, { method: "POST" })).json();
      const headers = {
        "X-Session-ID": fixture.session_id,
        "Content-Type": "application/json",
      };
      const root = `${api}/api/design/tasks/${fixture.task_id}`;
      const call = async (suffix, method = "GET", body) => {
        const response = await fetch(root + suffix, {
          method,
          headers,
          body: body ? JSON.stringify(body) : undefined,
        });
        assert.equal(response.status, 200, await response.clone().text());
        return response.json();
      };
      const space = {
        schema_version: "spatial/1.0",
        unit: "m",
        scale_status: "confirmed",
        source_image_id: null,
        rooms: [
          {
            id: "r",
            name: "客厅",
            height: 2.8,
            polygon: [
              { x: 0, z: 0 },
              { x: 6, z: 0 },
              { x: 6, z: 5 },
              { x: 0, z: 5 },
            ],
          },
        ],
        walls: [],
        openings: [],
      };
      await call("/space", "PUT", {
        base_version: 0,
        client_mutation_id: `material-space-${width}`,
        document: space,
      });
      await call("/home-design", "PUT", {
        base_version: 0,
        client_mutation_id: `material-home-${width}`,
        document: {
          schema_version: "home-design/1.0",
          space_version: 1,
          surfaces: [],
          objects: [],
        },
      });

      const context = await browser.newContext({
        viewport: { width, height: width === 390 ? 844 : 1000 },
      });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await context.route((url) => url.pathname.startsWith("/api/"), async (route) => {
        const target = new URL(route.request().url());
        if (
          target.pathname.startsWith("/api/design/tasks/") ||
          target.pathname === "/api/products/quote-rules"
        ) {
          const response = await route.fetch({
            url: api + target.pathname + target.search,
          });
          return route.fulfill({ response });
        }
        if (target.pathname.startsWith("/api/sessions")) {
          return route.fulfill({ json: { session_id: fixture.session_id } });
        }
        if (target.pathname === "/api/auth/me") {
          return route.fulfill({ status: 401, json: { detail: "未登录" } });
        }
        if (target.pathname === "/api/shop") {
          return route.fulfill({ json: { shop_name: "Haus" } });
        }
        return route.fulfill({ status: 404, json: { detail: "非本轮接口" } });
      });

      const openPanel = async (name) => {
        if (width === 390) {
          await page.getByRole("button", { name: "编辑与清单", exact: true }).click();
        }
        await page.getByRole("button", { name, exact: true }).click();
      };
      try {
        await page.goto(`${base}/design/${fixture.task_id}/home-design`);
        await page.locator(".hd-header small").filter({ hasText: "家装 V1" }).waitFor();
        await openPanel("表面材料");
        await page.getByLabel("材料名称", { exact: true }).fill("耐磨地板");
        const pricing = page.locator('select[name="quote_rule"]');
        const ruleOption = await pricing.evaluate((select) => {
          const option = [...select.options].find((item) =>
            item.textContent.includes("验收地面铺装"),
          );
          return option ? { value: option.value, text: option.textContent } : null;
        });
        assert(ruleOption);
        assert.match(ruleOption.text, /100元\/㎡.*v1/);
        await pricing.selectOption(ruleOption.value);
        await page.getByRole("button", { name: "应用饰面", exact: true }).click();
        const saveV2 = page.waitForResponse(
          (response) =>
            response.request().method() === "PUT" &&
            new URL(response.url()).pathname.endsWith("/home-design"),
        );
        await page.getByRole("button", { name: "保存草稿", exact: true }).click();
        assert.equal((await saveV2).status(), 200);
        await page.locator(".hd-header small").filter({ hasText: "家装 V2" }).waitFor();

        await openPanel("清单与比较");
        await page.getByLabel("估价地区代码", { exact: true }).fill("CN-SH");
        const quotedV2 = page.waitForResponse(
          (response) =>
            response.request().method() === "POST" &&
            new URL(response.url()).pathname.endsWith("/quotes"),
        );
        await page.getByRole("button", { name: "创建此版本估价", exact: true }).click();
        assert.equal((await quotedV2).status(), 200);
        await page.getByText("待报价：0 项", { exact: true }).waitFor();
        await page.getByText(/当前清单合计：3,600\.00 CNY/).waitFor();
        await page.getByText("估价明细（1 项）", { exact: true }).click();
        await page.getByText(/计价数据 browser-v1 · 规则 V1/).waitFor();

        const complete = await call("/home-design/quotes?home_version=2");
        assert.equal(complete.items.length, 1);
        const completeSnapshot = complete.items[0].snapshot;
        assert.equal(completeSnapshot.pending_count, 0);
        assert.equal(completeSnapshot.total_price, 3600);
        assert.equal(completeSnapshot.lines[0].quantity, 30);
        assert.equal(completeSnapshot.lines[0].source_data_version, "browser-v1");
        assert.equal(completeSnapshot.lines[0].source_version, 1);
        assert.match(completeSnapshot.lines[0].rule_evidence_digest, /^[a-f0-9]{64}$/);

        await openPanel("表面材料");
        await page.locator('select[name="kind"]').selectOption("ceiling");
        await page.getByLabel("材料名称", { exact: true }).fill("乳胶漆");
        await page.getByRole("button", { name: "应用饰面", exact: true }).click();
        const saveV3 = page.waitForResponse(
          (response) =>
            response.request().method() === "PUT" &&
            new URL(response.url()).pathname.endsWith("/home-design"),
        );
        await page.getByRole("button", { name: "保存草稿", exact: true }).click();
        assert.equal((await saveV3).status(), 200);
        await page.locator(".hd-header small").filter({ hasText: "家装 V3" }).waitFor();

        await openPanel("清单与比较");
        await page.getByLabel("估价地区代码", { exact: true }).fill("CN-SH");
        const quotedV3 = page.waitForResponse(
          (response) =>
            response.request().method() === "POST" &&
            new URL(response.url()).pathname.endsWith("/quotes"),
        );
        await page.getByRole("button", { name: "创建此版本估价", exact: true }).click();
        assert.equal((await quotedV3).status(), 200);
        await page.getByText("待报价：1 项", { exact: true }).waitFor();
        await page.getByText("估价明细（2 项）", { exact: true }).click();
        await page.getByText("尚未绑定材料计价规则", { exact: true }).waitFor();
        const pending = await call("/home-design/quotes?home_version=3");
        assert.equal(pending.items[0].snapshot.known_subtotal, 3600);
        assert.equal(pending.items[0].snapshot.total_price, null);
        assert.equal(pending.items[0].snapshot.pending_count, 1);

        await page.screenshot({
          path: `${output}/material-quote-${width}.png`,
          fullPage: true,
        });
        assert.equal(
          await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
          false,
        );
        assert.deepEqual(errors, []);
        checks.push({
          width,
          explicitRuleBinding: true,
          deterministicTotal: 3600,
          evidenceFrozen: true,
          unboundSurfacePending: true,
          mobileOverflow: false,
        });
      } catch (error) {
        await page.screenshot({
          path: `${output}/failure-${width}.png`,
          fullPage: true,
        });
        console.error(await page.locator("body").innerText());
        throw error;
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
  await fs.writeFile(
    `${output}/report.json`,
    JSON.stringify({ backend: "isolated_sqlite_real_api", checks }, null, 2),
  );
  console.log(JSON.stringify(checks));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
