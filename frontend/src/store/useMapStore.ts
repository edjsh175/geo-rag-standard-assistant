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

// ==================== 视角转换公式 (The Math Engine) ====================
// 完美的数学无缝转换：
// OpenLayers 基于 WebMercator (EPSG:3857)，赤道分辨率 = 156543.03392804097 / 2^zoom
// 实际维度的物理距离需要乘上 cos(latitude)。
// Cesium 的基于垂直视野角 (fov) 的相机，距地高度 height = (视锥体垂直地表范围 / 2) / tan(fov / 2)。
// 默认 Cesium vertical fov = Math.PI / 3 (60度)。

const R0 = 156543.03392804097;

/** 动态获取当前窗口大小（默认 1920x1080） */
const getViewportSize = () => {
  if (typeof window !== 'undefined') {
    return { w: window.innerWidth, h: window.innerHeight };
  }
  return { w: 1920, h: 1080 };
};

/** 
 * 计算 Cesium 当前的垂直半视场角的正切值 tan(fovy / 2)
 * Cesium 默认的 frustum.fov (Math.PI / 3) 作用于较长的那一边（通常是宽度）
 */
const getTanHalfFovy = (w: number, h: number) => {
  const tanHalfFov = Math.tan(Math.PI / 6); // fov/2 = 30度
  if (w > h) {
    // 宽屏：fov 决定 fovx，fovy 被 aspect ratio 压缩
    const aspect = w / h;
    return tanHalfFov / aspect;
  }
  // 竖屏：fov 决定 fovy
  return tanHalfFov;
};

/** OL zoom → Cesium camera height（米） */
export const zoomToHeight = (zoom: number, lat: number = 33.0): number => {
  const { w, h } = getViewportSize();
  const resAtEquator = R0 / Math.pow(2, zoom);
  const trueRes = resAtEquator * Math.cos(lat * Math.PI / 180);
  const visibleVerticalMeters = h * trueRes;
  
  const tanHalfFovy = getTanHalfFovy(w, h);
  return (visibleVerticalMeters / 2) / tanHalfFovy;
};

/** Cesium camera height → OL zoom */
export const heightToZoom = (height: number, lat: number = 33.0): number => {
  const { w, h } = getViewportSize();
  const tanHalfFovy = getTanHalfFovy(w, h);
  
  const visibleVerticalMeters = 2 * Math.max(height, 1) * tanHalfFovy;
  const trueRes = visibleVerticalMeters / h;
  const resAtEquator = trueRes / Math.cos(lat * Math.PI / 180);
  return Math.log2(R0 / resAtEquator);
};

// ==================== 初始视角（中国全貌） ====================
export const INITIAL_VIEW: MapViewState = {
  center: [104.0, 33.0], // 对齐 Cesium 中 [73.0, 12.0, 135.0, 54.0] 的矩阵中心
  zoom: 4.8,             // 保持 OL 的舒适展示 zoom
  height: zoomToHeight(4.8, 33.0), // 根据完美数学公式推导出的真实 3D 相机高度
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
