import type { RoomModel } from "./roomModel";

export interface UserRequirement {
  rooms: string[];
  area: number | null;
  houseType: string;
  city: string;
  renovationType: string;
  budgetRange: string;
  familySize: number;
  hasElderly: boolean;
  hasChildren: boolean;
  hasPets: boolean;
  workFromHome: boolean;
  cookingOften: boolean;
  needStorage: boolean;
  ecoFriendly: boolean;
  smartHome: boolean;
  styles: string[];
  colors: string[];
  dislikedColors: string[];
  materials: string[];
  extraNotes: string;
}

export const emptyRequirement: UserRequirement = {
  rooms: [],
  area: null,
  houseType: "",
  city: "",
  renovationType: "",
  budgetRange: "",
  familySize: 2,
  hasElderly: false,
  hasChildren: false,
  hasPets: false,
  workFromHome: false,
  cookingOften: false,
  needStorage: false,
  ecoFriendly: false,
  smartHome: false,
  styles: [],
  colors: [],
  dislikedColors: [],
  materials: [],
  extraNotes: "",
};

export interface ImageAnalysis {
  fileName: string;
  fileSize: string;
  /** 后端图片 id，用于尺寸校准等后续操作 */
  imageId?: number;
  findings: string[];
  suggestions?: string[];
  spaceType?: string;
  roomCount?: string;
  /** vl（真实视觉模型）/ placeholder（降级）/ mock（前端本地） */
  source?: string;
  /** VL 识别出的统一空间事实模型；降级时为 null */
  roomModel?: RoomModel | null;
}
