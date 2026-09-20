import { request } from "./designApi";
import type { HomeQuote, HomeQuoteList, HomeQuoteRequest } from "@/types/homeDesign";
export const createHomeQuote = (id: number, payload: HomeQuoteRequest) => request<HomeQuote>(`/api/design/tasks/${id}/home-design/quotes`, {method:"POST",body:JSON.stringify(payload)});
export const getHomeQuotes = (id: number, version: number, before?: number) => request<HomeQuoteList>(`/api/design/tasks/${id}/home-design/quotes?home_version=${version}&limit=10${before ? `&before_id=${before}` : ""}`);
export const getHomeQuote = (id: number, quoteId: number) => request<HomeQuote>(`/api/design/tasks/${id}/home-design/quotes/${quoteId}`);
import type {
  HomeAgentRequest,
  HomeAgentResponse,
  HomeAgentHistory,
} from "@/types/homeDesign";
export const requestHomeAgent = (id: number, payload: HomeAgentRequest) =>
  request<HomeAgentResponse>(
    `/api/design/tasks/${id}/home-design/agent-turns`,
    { method: "POST", body: JSON.stringify(payload) },
  );
export const getHomeAgentHistory = (id: number, before?: number) =>
  request<HomeAgentHistory>(
    `/api/design/tasks/${id}/home-design/agent-turns${before ? `?before_id=${before}` : ""}`,
  );
import type {
  HomeDesignResponse,
  HomeSaveRequest,
  HomeVersionList,
  HomeSpaceImpact,
  HomeSpaceImpactRequest,
} from "@/types/homeDesign";
import type { HomeDelivery, HomeComparison } from "@/types/homeDesign";
import type { HomeAsset, HomeAssetKind, HomeAssetOptions, HomeAssetRequest } from "@/types/homeDesign";
const path = (id: number) => `/api/design/tasks/${id}/home-design`;
export const previewHomeSpaceImpact = (id: number, payload: HomeSpaceImpactRequest) =>
  request<HomeSpaceImpact>(`${path(id)}/space-impact`, { method: "POST", body: JSON.stringify(payload) });
export const getHomeAssetOptions = (id: number, kind: HomeAssetKind, after?: number) =>
  request<HomeAssetOptions>(`${path(id)}/asset-options?kind=${kind}&limit=20${after ? `&after_id=${after}` : ""}`);
export const freezeHomeAsset = (id: number, payload: HomeAssetRequest) =>
  request<HomeAsset>(`${path(id)}/assets`, {method: "POST", body: JSON.stringify(payload)});
export const getHomeAsset = (id: number, assetId: number) =>
  request<HomeAsset>(`${path(id)}/assets/${assetId}`);
export const getHomeDesign = (id: number) =>
  request<HomeDesignResponse>(path(id));
export const saveHomeDesign = (id: number, payload: HomeSaveRequest) =>
  request<HomeDesignResponse>(path(id), {
    method: "PUT",
    body: JSON.stringify(payload),
  });
export const getHomeDesignVersion = (id: number, version: number) =>
  request<HomeDesignResponse>(`${path(id)}/versions/${version}`);
export const getHomeDesignVersions = (id: number, before?: number) =>
  request<HomeVersionList>(
    `${path(id)}/versions${before ? `?before_version=${before}` : ""}`,
  );
export const getHomeDelivery = (id: number, version: number) =>
  request<HomeDelivery>(`${path(id)}/versions/${version}/delivery`);
export const compareHomeDesigns = (id: number, from: number, to: number) =>
  request<HomeComparison>(
    `${path(id)}/compare?from_version=${from}&to_version=${to}`,
  );
