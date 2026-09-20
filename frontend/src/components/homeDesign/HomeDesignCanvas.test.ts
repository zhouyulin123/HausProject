import { describe, expect, it } from "vitest";
import { homeCanvasProfile } from "./HomeDesignCanvas";

describe("整屋三维渲染档位", () => {
  it("普通场景保留实时阴影", () => {
    expect(homeCanvasProfile(40)).toEqual({ shadows: true });
  });

  it("达到八十件时关闭高成本实时阴影", () => {
    expect(homeCanvasProfile(79)).toEqual({ shadows: true });
    expect(homeCanvasProfile(80)).toEqual({ shadows: false });
    expect(homeCanvasProfile(81)).toEqual({ shadows: false });
    expect(homeCanvasProfile(200)).toEqual({ shadows: false });
  });
});
