export type MapLayoutMode = 'standard' | 'chatExpanded';

export type MapPadding = [top: number, right: number, bottom: number, left: number];
export type ViewportSize = [width: number, height: number];
export type LonLatBounds = [west: number, south: number, east: number, north: number];

const STANDARD_CHAT_WIDTH = 420;
const EXPANDED_CHAT_WIDTH = 780;
const MIN_CHAT_WIDTH = 320;
const VIEWPORT_EDGE_GAP = 24;
const MAP_FIT_GUTTER = 40;
const PANEL_TO_MAP_GAP = 40;

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

export const getChatPanelWidth = (
  mode: MapLayoutMode,
  viewportWidth = typeof window === 'undefined' ? 1920 : window.innerWidth
) => {
  const targetWidth = mode === 'chatExpanded' ? EXPANDED_CHAT_WIDTH : STANDARD_CHAT_WIDTH;
  const maxWidth = Math.max(MIN_CHAT_WIDTH, viewportWidth - VIEWPORT_EDGE_GAP * 2);

  return Math.round(clamp(targetWidth, MIN_CHAT_WIDTH, maxWidth));
};

export const getMapFitPadding = (
  mode: MapLayoutMode,
  viewportWidth = typeof window === 'undefined' ? 1920 : window.innerWidth
): MapPadding => {
  const panelWidth = getChatPanelWidth(mode, viewportWidth);
  const right = panelWidth + VIEWPORT_EDGE_GAP + PANEL_TO_MAP_GAP;

  return [MAP_FIT_GUTTER, right, MAP_FIT_GUTTER, MAP_FIT_GUTTER];
};

export const expandBoundsForPadding = (
  bounds: LonLatBounds,
  padding: MapPadding,
  viewport: ViewportSize
): LonLatBounds => {
  const [west, south, east, north] = bounds;
  const [viewportWidth, viewportHeight] = viewport;
  const [top, right, bottom, left] = padding;
  const safeWidth = Math.max(1, viewportWidth - left - right);
  const safeHeight = Math.max(1, viewportHeight - top - bottom);
  const width = Math.max(0.000001, east - west);
  const height = Math.max(0.000001, north - south);

  return [
    clamp(west - width * (left / safeWidth), -180, 180),
    clamp(south - height * (bottom / safeHeight), -90, 90),
    clamp(east + width * (right / safeWidth), -180, 180),
    clamp(north + height * (top / safeHeight), -90, 90),
  ];
};
