import { describe, expect, it } from "vitest";
import {
  createSpatialParticles,
  getRevealProgress,
  getScanPosition,
} from "./spatialMotion";

describe("spatialMotion", () => {
  it("按延迟与时长生成平滑且受限的显现进度", () => {
    expect(getRevealProgress(0.5, 1, 2)).toBe(0);
    expect(getRevealProgress(2, 1, 2)).toBeCloseTo(0.5);
    expect(getRevealProgress(4, 1, 2)).toBe(1);
  });

  it("扫描位置在指定跨度内循环", () => {
    expect(getScanPosition(0, 10, 5)).toBe(-5);
    expect(getScanPosition(2.5, 10, 5)).toBeCloseTo(0);
    expect(getScanPosition(5, 10, 5)).toBe(-5);
  });

  it("生成可复现且位于空间边界内的粒子", () => {
    const first = createSpatialParticles(8, 42);
    const second = createSpatialParticles(8, 42);
    expect(first).toEqual(second);
    expect(first).toHaveLength(24);
    expect(first.every((value) => Number.isFinite(value))).toBe(true);
    expect(Math.max(...first.map(Math.abs))).toBeLessThanOrEqual(6);
  });

  it("按房间边界与中心点生成覆盖完整空间的粒子场", () => {
    const particles = createSpatialParticles(320, 23, {
      width: 4.6,
      depth: 5.6,
      height: 2.8,
      centerX: 1.4,
      centerZ: -0.8,
      padding: 0.6,
    });
    const xs = particles.filter((_, index) => index % 3 === 0);
    const ys = particles.filter((_, index) => index % 3 === 1);
    const zs = particles.filter((_, index) => index % 3 === 2);

    expect(Math.min(...xs)).toBeGreaterThanOrEqual(-1.5);
    expect(Math.max(...xs)).toBeLessThanOrEqual(4.3);
    expect(Math.min(...zs)).toBeGreaterThanOrEqual(-4.2);
    expect(Math.max(...zs)).toBeLessThanOrEqual(2.6);
    expect(Math.min(...xs)).toBeLessThan(1.4);
    expect(Math.max(...xs)).toBeGreaterThan(1.4);
    expect(Math.min(...zs)).toBeLessThan(-0.8);
    expect(Math.max(...zs)).toBeGreaterThan(-0.8);
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(0.08);
    expect(Math.max(...ys)).toBeLessThanOrEqual(2.88);
  });
});
