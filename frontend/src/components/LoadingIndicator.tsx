import React from 'react';
import { cn } from '../lib/utils';

export interface LoadingIndicatorProps {
  /** 加载文本 */
  text?: string;
  /** 是否使用点状动画 */
  dotAnimation?: boolean;
  /** 是否使用骨架屏 */
  skeleton?: boolean;
  /** 自定义类名 */
  className?: string;
  /** 文本类名 */
  textClassName?: string;
}

/**
 * 优雅的加载反馈组件
 * 提供类似ChatGPT的呼吸小圆点动画或骨架屏效果
 */
const LoadingIndicator: React.FC<LoadingIndicatorProps> = ({
  text = '正在加载...',
  dotAnimation = true,
  skeleton = false,
  className,
  textClassName,
}) => {
  if (skeleton) {
    return (
      <div className={cn('space-y-3', className)}>
        <div className="flex items-center space-x-2">
          <div className="w-2 h-2 bg-primary/30 rounded-full animate-pulse" />
          <div className="w-2 h-2 bg-primary/30 rounded-full animate-pulse delay-75" />
          <div className="w-2 h-2 bg-primary/30 rounded-full animate-pulse delay-150" />
        </div>
        <div className="h-4 bg-surface-container-highest rounded w-3/4 animate-pulse" />
        <div className="h-4 bg-surface-container-highest rounded w-1/2 animate-pulse delay-100" />
      </div>
    );
  }

  if (dotAnimation) {
    return (
      <div className={cn('flex items-center gap-4', className)}>
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full" style={{ background: 'rgba(240,112,64,0.06)', border: '0.5px solid rgba(240,112,64,0.15)' }}>
          <div className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse-soft" style={{ boxShadow: '0 0 8px rgba(240,112,64,0.5)' }} />
          <div className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse-soft [animation-delay:0.4s]" style={{ boxShadow: '0 0 8px rgba(240,112,64,0.5)' }} />
          <div className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse-soft [animation-delay:0.8s]" style={{ boxShadow: '0 0 8px rgba(240,112,64,0.5)' }} />
        </div>
        {text && (
          <span className={cn('text-[13.5px] font-medium tracking-wide uppercase italic', textClassName)} style={{ color: 'rgba(240,112,64,0.65)' }}>
            {text}
          </span>
        )}
      </div>
    );
  }

  // 默认使用简洁的动画
  return (
    <div className={cn('flex items-center gap-3', className)}>
      <div className="relative">
        <div className="w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
      </div>
      {text && (
        <span className={cn('text-sm opacity-60 text-on-background', textClassName)}>
          {text}
        </span>
      )}
    </div>
  );
};

export default LoadingIndicator;