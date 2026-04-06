import { create } from 'zustand';

// ============================================================
//  GeoAI 全局空间状态中枢 (Global Spatial Store)
//  所有省份点击 / 视角变更都必须先写入此 Store，
//  再由各引擎（OL / Cesium）订阅响应——杜绝组件内"自嗨"。
// ============================================================

/** 当前高亮的行政区划 */
export interface ActiveRegion {
  adcode: string;
  name: string;
}

/** 统一视角参数（2D/3D 共用，切换时互相转换） */
export interface MapViewState {
  center: [number, number];   // [longitude, latitude] WGS84
  zoom: number;               // OL 缩放级别
  height: number;             // Cesium 相机高度（米）
}

// ==================== 视角转换公式 ====================
// 近似关系：Cesium height ≈ 35_200_000 / 2^zoom
// 逆推：zoom ≈ log2(35_200_000 / height)

/** OL zoom → Cesium camera height（米） */
export const zoomToHeight = (zoom: number): number =>
  35_200_000 / Math.pow(2, zoom);

/** Cesium camera height → OL zoom */
export const heightToZoom = (height: number): number =>
  Math.log2(35_200_000 / Math.max(height, 1));

// ==================== 初始视角（中国全貌） ====================
export const INITIAL_VIEW: MapViewState = {
  center: [104.0665, 30.5723],
  zoom: 4,
  height: zoomToHeight(4), // ≈ 2_200_000m
};

// ==================== Store 定义 ====================
interface MapStore {
  /** 当前选中省份，null 表示全国总览 */
  activeRegion: ActiveRegion | null;

  /** 当前视角参数 */
  viewState: MapViewState;

  /** 当前 2D/3D 模式 */
  viewMode: '2D' | '3D';

  /** 递增计数器，每次 +1 触发地图引擎执行 flyTo 动画 */
  flyTrigger: number;

  // —————————— Actions ——————————

  /** 选中某省份（任何来源：OL 点击、Cesium 点击、AI 回复） */
  setActiveRegion: (region: ActiveRegion | null) => void;

  /** 写入视角参数（切换引擎前由当前引擎调用） */
  setViewState: (patch: Partial<MapViewState>) => void;

  /** 切换 2D / 3D 模式 */
  setViewMode: (mode: '2D' | '3D') => void;

  /** 复位：清空选中 + 回到中国全貌 */
  resetView: () => void;

  /** 手动触发一次 flyTo（用于 setActiveRegion 后让两个引擎同步飞行） */
  triggerFly: () => void;
}

export const useMapStore = create<MapStore>((set) => ({
  activeRegion: null,
  viewState: { ...INITIAL_VIEW },
  viewMode: '3D',
  flyTrigger: 0,

  setActiveRegion: (region) =>
    set((s) => ({
      activeRegion: region,
      flyTrigger: s.flyTrigger + 1,   // 自动触发 flyTo
    })),

  setViewState: (patch) =>
    set((s) => ({
      viewState: { ...s.viewState, ...patch },
    })),

  setViewMode: (mode) => set({ viewMode: mode }),

  resetView: () =>
    set((s) => ({
      activeRegion: null,
      viewState: { ...INITIAL_VIEW },
      flyTrigger: s.flyTrigger + 1,   // 触发回到初始视角的动画
    })),

  triggerFly: () =>
    set((s) => ({ flyTrigger: s.flyTrigger + 1 })),
}));
