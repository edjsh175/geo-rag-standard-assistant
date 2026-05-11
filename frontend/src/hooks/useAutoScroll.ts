import { useCallback, useEffect, useRef, useState } from 'react';

export interface UseAutoScrollOptions {
  threshold?: number;
  behavior?: ScrollBehavior;
  onScrollComplete?: () => void;
}

export const useAutoScroll = (
  containerRef: React.RefObject<HTMLElement>,
  options: UseAutoScrollOptions = {}
) => {
  const { threshold = 50, behavior = 'smooth' } = options;

  const [isAutoScrollLocked, setIsAutoScrollLocked] = useState(false);
  const scrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastScrollTopRef = useRef(0);
  const isUserScrollingRef = useRef(false);
  const isProgrammaticScrollingRef = useRef(false);

  const scrollToBottom = useCallback(
    (customOptions?: Partial<UseAutoScrollOptions>) => {
      const container = containerRef.current;
      if (!container) return;

      const { behavior: customBehavior = behavior } = customOptions || {};
      isProgrammaticScrollingRef.current = true;

      requestAnimationFrame(() => {
        setTimeout(() => {
          const currentContainer = containerRef.current;
          if (!currentContainer) {
            isProgrammaticScrollingRef.current = false;
            return;
          }

          const targetScrollTop =
            currentContainer.scrollHeight - currentContainer.clientHeight;

          if (targetScrollTop > 0) {
            currentContainer.scrollTo({
              top: targetScrollTop,
              behavior: customBehavior,
            });

            const scrollDuration = customBehavior === 'smooth' ? 300 : 0;
            setTimeout(() => {
              isProgrammaticScrollingRef.current = false;
            }, scrollDuration);
          } else {
            isProgrammaticScrollingRef.current = false;
          }
        }, 100);
      });
    },
    [behavior, containerRef]
  );

  const lockAutoScroll = useCallback(() => {
    setIsAutoScrollLocked(true);
  }, []);

  const unlockAutoScroll = useCallback(() => {
    setIsAutoScrollLocked(false);
  }, []);

  const isAtBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) return true;

    const { scrollTop, scrollHeight, clientHeight } = container;
    const distanceToBottom = scrollHeight - scrollTop - clientHeight;
    return distanceToBottom <= threshold;
  }, [containerRef, threshold]);

  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const { scrollTop } = container;
    const isAtBottomNow = isAtBottom();
    const scrollDelta = Math.abs(scrollTop - lastScrollTopRef.current);
    lastScrollTopRef.current = scrollTop;

    if (!isProgrammaticScrollingRef.current && scrollDelta > 5) {
      isUserScrollingRef.current = true;

      if (scrollTimerRef.current) {
        clearTimeout(scrollTimerRef.current);
      }

      scrollTimerRef.current = setTimeout(() => {
        isUserScrollingRef.current = false;
      }, 150);
    }

    if (isAtBottomNow) {
      unlockAutoScroll();
    } else if (
      !isProgrammaticScrollingRef.current &&
      isUserScrollingRef.current &&
      !isAutoScrollLocked
    ) {
      lockAutoScroll();
    }
  }, [containerRef, isAtBottom, isAutoScrollLocked, lockAutoScroll, unlockAutoScroll]);

  const resetScrollState = useCallback(() => {
    setIsAutoScrollLocked(false);
    isUserScrollingRef.current = false;
    isProgrammaticScrollingRef.current = false;
    lastScrollTopRef.current = 0;
  }, []);

  useEffect(() => {
    resetScrollState();
  }, [containerRef, resetScrollState]);

  useEffect(() => {
    return () => {
      if (scrollTimerRef.current) {
        clearTimeout(scrollTimerRef.current);
      }
    };
  }, []);

  return {
    scrollToBottom,
    lockAutoScroll,
    unlockAutoScroll,
    isAutoScrollLocked,
    isAtBottom,
    resetScrollState,
    handleScroll,
  };
};

export default useAutoScroll;
