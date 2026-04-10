import { useRef, useCallback, useState, useEffect } from 'react';

export interface UseAutoScrollOptions {
  /** 触发自动滚动恢复的阈值（距离底部的像素） */
  threshold?: number;
  /** 滚动行为 */
  behavior?: ScrollBehavior;
  /** 滚动完成后回调 */
  onScrollComplete?: () => void;
}

/**
 * 智能防冲突滚动 Hook
 * 提供自动滚动功能，同时尊重用户的手动滚动控制
 */
export const useAutoScroll = (
  containerRef: React.RefObject<HTMLElement>,
  options: UseAutoScrollOptions = {}
) => {
  const { threshold = 50, behavior = 'smooth' } = options;

  // 自动滚动锁定状态（用户手动滚动时锁定）
  const [isAutoScrollLocked, setIsAutoScrollLocked] = useState(false);
  // 防抖定时器引用
  const scrollTimerRef = useRef<NodeJS.Timeout | null>(null);
  // 最后一次滚动位置
  const lastScrollTopRef = useRef(0);
  // 用户滚动标志
  const isUserScrollingRef = useRef(false);
  // 程序滚动标志（避免程序滚动触发锁定）
  const isProgrammaticScrollingRef = useRef(false);

  /**
   * 滚动到底部
   */
  const scrollToBottom = useCallback((customOptions?: Partial<UseAutoScrollOptions>) => {
    const container = containerRef.current;
    if (!container) {
      console.warn('[useAutoScroll] scrollToBottom: 容器不存在');
      return;
    }

    const { behavior: customBehavior = behavior } = customOptions || {};

    console.log('[useAutoScroll] scrollToBottom 触发', {
      scrollHeight: container.scrollHeight,
      clientHeight: container.clientHeight,
      scrollTop: container.scrollTop,
      behavior: customBehavior,
      isAutoScrollLocked,
    });

    // 标记为程序滚动，避免触发自动滚动锁定
    isProgrammaticScrollingRef.current = true;

    // 使用双重延迟：requestAnimationFrame + setTimeout 确保 DOM 完全渲染
    requestAnimationFrame(() => {
      // 额外延迟 100ms 确保 React DOM 更新完成
      setTimeout(() => {
        // 重新获取容器引用，确保获取的是最新的 DOM 状态
        const currentContainer = containerRef.current;
        if (!currentContainer) {
          console.warn('[useAutoScroll] scrollToBottom: 容器在延迟后不存在');
          isProgrammaticScrollingRef.current = false;
          return;
        }

        const targetScrollTop = currentContainer.scrollHeight - currentContainer.clientHeight;
        console.log('[useAutoScroll] 执行滚动到:', targetScrollTop, {
          当前scrollTop: currentContainer.scrollTop,
          差值: targetScrollTop - currentContainer.scrollTop,
        });

        if (targetScrollTop > 0) {
          currentContainer.scrollTo({
            top: targetScrollTop,
            behavior: customBehavior,
          });

          // 平滑滚动的持续时间大约为 300ms，之后清除程序滚动标志
          const scrollDuration = customBehavior === 'smooth' ? 300 : 0;
          setTimeout(() => {
            isProgrammaticScrollingRef.current = false;
            console.log('[useAutoScroll] 程序滚动标志已清除');
          }, scrollDuration);
        } else {
          console.warn('[useAutoScroll] 目标滚动位置 <= 0，跳过滚动');
          isProgrammaticScrollingRef.current = false;
        }
      }, 100); // 关键延迟，等待 React DOM 挂载完成
    });
  }, [containerRef, behavior, isAutoScrollLocked]);

  /**
   * 锁定自动滚动（用户开始手动滚动时调用）
   */
  const lockAutoScroll = useCallback(() => {
    setIsAutoScrollLocked(true);
  }, []);

  /**
   * 解锁自动滚动（用户滚动回底部时调用）
   */
  const unlockAutoScroll = useCallback(() => {
    setIsAutoScrollLocked(false);
  }, []);

  /**
   * 检查是否在底部阈值内
   */
  const isAtBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) {
      console.warn('[useAutoScroll] isAtBottom: 容器不存在');
      return true;
    }

    const { scrollTop, scrollHeight, clientHeight } = container;
    const distanceToBottom = scrollHeight - scrollTop - clientHeight;
    const isBottom = distanceToBottom <= threshold;

    // 调试日志，可注释掉
    // console.log('[useAutoScroll] isAtBottom 检查', {
    //   scrollHeight,
    //   clientHeight,
    //   scrollTop,
    //   distanceToBottom,
    //   threshold,
    //   isBottom,
    // });

    return isBottom;
  }, [containerRef, threshold]);

  /**
   * 处理滚动事件
   */
  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) {
      console.warn('[useAutoScroll] handleScroll: 容器不存在');
      return;
    }

    const { scrollTop, scrollHeight, clientHeight } = container;
    const isAtBottomNow = isAtBottom();

    // 检测滚动方向（仅在滚动位置变化较大时）
    const scrollDelta = Math.abs(scrollTop - lastScrollTopRef.current);
    lastScrollTopRef.current = scrollTop;

    // 如果不是程序滚动且滚动距离较大，认为是用户手动滚动
    if (!isProgrammaticScrollingRef.current && scrollDelta > 5) {
      console.log('[useAutoScroll] 检测到用户手动滚动', {
        scrollDelta,
        scrollTop,
        isProgrammaticScrolling: isProgrammaticScrollingRef.current,
      });

      isUserScrollingRef.current = true;

      // 清除之前的定时器
      if (scrollTimerRef.current) {
        clearTimeout(scrollTimerRef.current);
      }

      // 设置定时器，一段时间后重置用户滚动标志
      scrollTimerRef.current = setTimeout(() => {
        isUserScrollingRef.current = false;
        console.log('[useAutoScroll] 用户滚动标志已重置');
      }, 150);
    }

    // 如果在底部，解锁自动滚动（无论是用户滚动还是程序滚动）
    if (isAtBottomNow) {
      console.log('[useAutoScroll] 在底部区域，解锁自动滚动', {
        distanceToBottom: scrollHeight - scrollTop - clientHeight,
        threshold,
      });
      unlockAutoScroll();
    }
    // 如果不在底部且用户正在滚动且不是程序滚动，锁定自动滚动
    else if (!isProgrammaticScrollingRef.current && isUserScrollingRef.current && !isAutoScrollLocked) {
      console.log('[useAutoScroll] 不在底部且用户正在滚动，锁定自动滚动', {
        isAtBottomNow,
        isUserScrolling: isUserScrollingRef.current,
        isAutoScrollLocked,
      });
      lockAutoScroll();
    }
  }, [containerRef, isAtBottom, isAutoScrollLocked, lockAutoScroll, unlockAutoScroll, threshold]);

  /**
   * 重置滚动状态
   */
  const resetScrollState = useCallback(() => {
    setIsAutoScrollLocked(false);
    isUserScrollingRef.current = false;
    lastScrollTopRef.current = 0;
  }, []);

  // 容器变化时重置状态
  useEffect(() => {
    resetScrollState();
  }, [containerRef.current]);

  // 清理定时器
  useEffect(() => {
    return () => {
      if (scrollTimerRef.current) {
        clearTimeout(scrollTimerRef.current);
      }
    };
  }, []);

  return {
    /** 滚动到底部 */
    scrollToBottom,
    /** 锁定自动滚动 */
    lockAutoScroll,
    /** 解锁自动滚动 */
    unlockAutoScroll,
    /** 是否自动滚动被锁定 */
    isAutoScrollLocked,
    /** 检查是否在底部 */
    isAtBottom,
    /** 重置滚动状态 */
    resetScrollState,
    /** 处理滚动事件（供外部调用） */
    handleScroll,
  };
};

export default useAutoScroll;