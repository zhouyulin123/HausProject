/** V2 大场景单次实测：不是统计 p95，不连接业务数据库。 */
const { chromium } = require("playwright");
const sharp = require("sharp");
const fs = require("node:fs/promises");
const path = require("node:path");
const assert = require("node:assert/strict");

const base = process.env.HAUS_BROWSER_BASE || "http://127.0.0.1:8085";
const api = process.env.HAUS_SPATIAL_TEST_API || "http://127.0.0.1:8083";

async function nonBlank(buffer) {
  const stats = await sharp(buffer).stats();
  return stats.channels.some((channel) => channel.stdev > 4);
}

async function waitForNonBlank(locator, timeout = 15000) {
  const started = performance.now();
  while (performance.now() - started < timeout) {
    const image = await locator.screenshot();
    if (await nonBlank(image)) return { image, elapsedMs: performance.now() - started };
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw Error("3D 画布在限定时间内未出现非空画面");
}

async function main() {
  for (const url of [base, api]) {
    assert(["127.0.0.1", "localhost"].includes(new URL(url).hostname));
  }
  const output = path.resolve("outputs/v2-large-scene");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const checks = [];
  try {
    for (const scenario of [
      { width: 1440, height: 1000, frozen: 120, concepts: 80 },
      { width: 390, height: 844, frozen: 48, concepts: 32 },
    ]) {
      const fixtureResponse = await fetch(`${api}/fixture`, { method: "POST" });
      assert.equal(fixtureResponse.status, 200, await fixtureResponse.clone().text());
      const fixture = await fixtureResponse.json();
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
            id: "large-room",
            name: "大场景验收空间",
            height: 3,
            polygon: [
              { x: 0, z: 0 },
              { x: 40, z: 0 },
              { x: 40, z: 24 },
              { x: 0, z: 24 },
            ],
          },
        ],
        walls: [],
        openings: [],
      };
      await call("/space", "PUT", {
        base_version: 0,
        client_mutation_id: `large-space-${scenario.width}`,
        document: space,
      });
      const options = await call("/home-design/asset-options?kind=product&limit=20");
      const option = options.items.find((item) => item.available);
      assert(option, "隔离目录没有可冻结的家具");
      const asset = await call("/home-design/assets", "POST", {
        client_mutation_id: `large-asset-${scenario.width}`,
        kind: option.kind,
        source_id: option.source_id,
        source_version: option.source_version,
      });
      const total = scenario.frozen + scenario.concepts;
      const objects = Array.from({ length: total }, (_, index) => {
        const position = {
          x: 1 + (index % 20) * 1.9,
          y: 0,
          z: 1 + Math.floor(index / 20) * 2,
        };
        if (index < scenario.frozen) {
          return {
            id: `frozen-${index}`,
            asset_id: asset.id,
            room_id: "large-room",
            name: `冻结家具 ${index + 1}`,
            category: "furniture",
            position,
            size: asset.size,
            rotation: (index % 4) * 90,
            material: asset.material,
          };
        }
        return {
          id: `concept-${index}`,
          room_id: "large-room",
          name: `概念体块 ${index - scenario.frozen + 1}`,
          category: "furniture",
          position,
          size: { width: 0.65, height: 0.55, depth: 0.65 },
          rotation: 0,
          material: { name: "概念材料", color: "#88a79a" },
        };
      });
      await call("/home-design", "PUT", {
        base_version: 0,
        client_mutation_id: `large-home-${scenario.width}`,
        document: {
          schema_version: "home-design/1.0",
          space_version: 1,
          surfaces: [],
          objects,
        },
      });

      const context = await browser.newContext({
        viewport: { width: scenario.width, height: scenario.height },
      });
      const page = await context.newPage();
      const errors = [];
      let assetRequests = 0;
      page.on("pageerror", (error) => errors.push(error.message));
      await context.route((url) => url.pathname.startsWith("/api/"), async (route) => {
        const target = new URL(route.request().url());
        if (/\/home-design\/assets\/\d+$/.test(target.pathname)) assetRequests += 1;
        if (/\/(space|home-design)(\/|$)/.test(target.pathname)) {
          return route.fulfill({
            response: await route.fetch({ url: api + target.pathname + target.search }),
          });
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

      try {
        const navigationStarted = performance.now();
        await page.goto(`${base}/design/${fixture.task_id}/home-design`);
        await page.getByText(/家装 V1/).waitFor();
        const plan = page.locator("svg.hd-plan");
        await plan.waitFor();
        await page.getByRole("button", { name: "选择冻结家具 1", exact: true }).click();
        const interactive2dMs = performance.now() - navigationStarted;
        assert.equal(assetRequests, 0, "2D 模式不应请求 3D 冻结家具资产");
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);

        const switchStarted = performance.now();
        if (scenario.width === 390) {
          await page.getByRole("button", { name: "当前方案", exact: true }).click();
        }
        await page.getByRole("button", { name: "3D", exact: true }).click();
        const canvas = page.locator("canvas");
        await canvas.waitFor();
        const first = await waitForNonBlank(canvas);
        const firstNonBlank3dMs = performance.now() - switchStarted;
        assert.equal(assetRequests, 1, "重复引用同一 asset_id 只应请求一次模型");
        const box = await canvas.boundingBox();
        assert(box && box.width > 0 && box.height > 0);
        await page.mouse.move(box.x + box.width * 0.42, box.y + box.height * 0.5);
        await page.mouse.down();
        await page.mouse.move(box.x + box.width * 0.64, box.y + box.height * 0.58, { steps: 14 });
        await page.mouse.up();
        await page.waitForTimeout(250);
        const rotated = await canvas.screenshot();
        assert(!first.image.equals(rotated), "拖拽后 3D 画面应发生变化");
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        assert.deepEqual(errors, []);
        await page.screenshot({
          path: path.join(output, `large-scene-${scenario.width}.png`),
          fullPage: true,
        });
        checks.push({
          viewport: { width: scenario.width, height: scenario.height },
          object_count: total,
          repeated_frozen_object_count: scenario.frozen,
          concept_object_count: scenario.concepts,
          unique_asset_count: 1,
          observed_single_run_ms: {
            navigation_to_2d_interactive: Math.round(interactive2dMs),
            switch_to_first_non_blank_3d: Math.round(firstNonBlank3dMs),
            non_blank_probe: Math.round(first.elapsedMs),
          },
          asset_requests_before_3d: 0,
          asset_requests_after_3d: assetRequests,
          canvas_non_blank: true,
          rotation_changed_pixels: true,
          horizontal_overflow: false,
          page_errors: [],
        });
      } catch (error) {
        await page.screenshot({
          path: path.join(output, `failure-${scenario.width}.png`),
          fullPage: true,
        });
        throw error;
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
  const report = {
    schema_version: "v2-large-scene-browser/1.0",
    measured_at: new Date().toISOString(),
    measurement_kind: "single_local_run_not_p95",
    backend: "isolated_sqlite_real_api",
    checks,
  };
  await fs.writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
