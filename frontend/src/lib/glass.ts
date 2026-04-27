import type { CSSProperties } from 'react';

export const glassStyle: CSSProperties = {
  backdropFilter: 'blur(20px) saturate(180%)',
  WebkitBackdropFilter: 'blur(20px) saturate(180%)',
};

export const glassLightStyle: CSSProperties = {
  backdropFilter: 'blur(16px) saturate(160%)',
  WebkitBackdropFilter: 'blur(16px) saturate(160%)',
};

export const drawerGlassStyle: CSSProperties = {
  backdropFilter: 'blur(32px)',
  WebkitBackdropFilter: 'blur(32px)',
};
