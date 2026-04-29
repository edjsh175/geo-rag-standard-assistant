import { ArrowRight, CheckCircle2, LoaderCircle, MapPinned, RefreshCcw } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';

import { useResolvedTheme } from '../lib/theme';
import { cn } from '../lib/utils';

export type BootScreenPhase = 'loading' | 'ready' | 'entering';

interface BootScreenProps {
  title?: string;
  status: string;
  detail?: string;
  error?: string | null;
  actionLabel?: string;
  onAction?: () => void;
  compact?: boolean;
  phase?: BootScreenPhase;
  primaryActionLabel?: string;
  onPrimaryAction?: () => void;
}

export default function BootScreen({
  title = 'GeoAI 空间规划智能检索与可视化系统',
  status,
  detail,
  error,
  actionLabel = '重新尝试',
  onAction,
  compact = false,
  phase = 'loading',
  primaryActionLabel = '进入系统',
  onPrimaryAction,
}: BootScreenProps) {
  const theme = useResolvedTheme();
  const isLight = theme === 'light';
  const reduceMotion = useReducedMotion();

  const isReady = phase === 'ready' && !error;
  const isEntering = phase === 'entering' && !error;

  const overlayTransition = reduceMotion
    ? { duration: 0.24, ease: 'easeOut' as const }
    : { duration: 0.9, ease: [0.22, 1, 0.36, 1] as const };

  const cardTransition = reduceMotion
    ? { duration: 0.2, ease: 'easeOut' as const }
    : { duration: 0.72, ease: [0.22, 1, 0.36, 1] as const };

  return (
    <motion.div
      className={cn(
        'absolute inset-0 z-[120] flex items-center justify-center overflow-hidden',
        compact ? 'bg-background/92 backdrop-blur-xl' : 'bg-background'
      )}
      initial={false}
      animate={{
        opacity: isEntering ? 0 : 1,
      }}
      transition={overlayTransition}
    >
      <motion.div
        className="absolute inset-0"
        initial={false}
        animate={{
          opacity: isEntering ? (reduceMotion ? 0.08 : 0) : 1,
          scale: isEntering ? (reduceMotion ? 1.01 : 1.05) : 1,
        }}
        transition={overlayTransition}
        style={{
          background: isLight
            ? 'radial-gradient(circle at top, rgba(240,112,64,0.12), transparent 34%), radial-gradient(circle at bottom right, rgba(28,28,33,0.06), transparent 24%)'
            : 'radial-gradient(circle at top, rgba(240,112,64,0.18), transparent 35%), radial-gradient(circle at bottom right, rgba(255,255,255,0.08), transparent 28%)',
        }}
      />

      <motion.div
        className="absolute inset-0 [background-size:48px_48px]"
        initial={false}
        animate={{
          opacity: isEntering ? 0 : isLight ? 0.16 : 0.3,
        }}
        transition={overlayTransition}
        style={{
          backgroundImage: isLight
            ? 'linear-gradient(rgba(0,0,0,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.045) 1px, transparent 1px)'
            : 'linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)',
        }}
      />

      <section className="relative w-full max-w-xl px-6">
        <motion.div
          className="glass rounded-[28px] border border-outline/60 px-8 py-10"
          initial={false}
          animate={{
            opacity: isEntering ? 0 : 1,
            y: isEntering ? (reduceMotion ? -8 : -36) : 0,
            scale: isEntering ? (reduceMotion ? 0.99 : 0.965) : 1,
            filter: isEntering ? 'blur(10px)' : 'blur(0px)',
          }}
          transition={cardTransition}
          style={{
            boxShadow: isLight
              ? '0 24px 80px rgba(17, 24, 39, 0.12)'
              : '0 24px 80px rgba(0,0,0,0.35)',
          }}
        >
          <div className="mb-8 flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-primary-container/30 bg-primary-container/10 shadow-[0_0_24px_rgba(240,112,64,0.18)]">
              {isReady ? (
                <CheckCircle2 className="h-6 w-6 text-primary-container" />
              ) : (
                <MapPinned className="h-6 w-6 text-primary-container" />
              )}
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-primary-container/70">
                Sentinel GeoAI
              </p>
              <h1 className="mt-1 font-headline text-2xl font-semibold text-on-background">
                {title}
              </h1>
            </div>
          </div>

          <div
            className="rounded-2xl border border-outline/50 px-5 py-4"
            style={{ background: isLight ? 'rgba(255,255,255,0.58)' : 'rgba(255,255,255,0.03)' }}
          >
            <div className="flex items-center gap-3">
              {isReady ? (
                <CheckCircle2 className="h-5 w-5 text-primary-container" />
              ) : (
                <LoaderCircle
                  className={cn(
                    'h-5 w-5 text-primary-container',
                    !error && 'animate-spin'
                  )}
                />
              )}
              <div>
                <p className="text-sm font-semibold text-on-background">{status}</p>
                {detail ? (
                  <p className="mt-1 text-sm text-on-background/55">{detail}</p>
                ) : null}
              </div>
            </div>
          </div>

          {error ? (
            <div
              className="mt-5 rounded-2xl border px-5 py-4"
              style={{
                borderColor: isLight ? 'rgba(220,38,38,0.18)' : 'rgba(239,68,68,0.2)',
                background: isLight ? 'rgba(239,68,68,0.07)' : 'rgba(239,68,68,0.08)',
              }}
            >
              <p className={cn('text-sm font-medium', isLight ? 'text-red-700' : 'text-red-200')}>{error}</p>
              {onAction ? (
                <button
                  type="button"
                  onClick={onAction}
                  className={cn(
                    'mt-4 inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold transition',
                    isLight
                      ? 'border-red-500/20 bg-red-500/8 text-red-700 hover:bg-red-500/12'
                      : 'border-red-400/25 bg-red-400/10 text-red-100 hover:bg-red-400/16'
                  )}
                >
                  <RefreshCcw className="h-4 w-4" />
                  {actionLabel}
                </button>
              ) : null}
            </div>
          ) : isReady ? (
            <motion.div
              className="mt-6 rounded-[24px] border border-outline/50 px-5 py-5"
              initial={false}
              animate={{
                opacity: 1,
                y: 0,
              }}
              transition={cardTransition}
              style={{
                background: isLight
                  ? 'linear-gradient(180deg, rgba(255,255,255,0.72), rgba(255,255,255,0.48))'
                  : 'linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02))',
              }}
            >
              <div className="mb-5 flex items-center justify-between text-sm text-on-background/58">
                <span>地图、会话和资源已经完成就绪检查</span>
                <span className="font-mono text-primary-container/80">READY</span>
              </div>
              <button
                type="button"
                onClick={onPrimaryAction}
                className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-primary-container px-5 py-3.5 text-sm font-semibold text-on-primary-fixed transition hover:brightness-105"
              >
                <span>{primaryActionLabel}</span>
                <ArrowRight className="h-4 w-4" />
              </button>
            </motion.div>
          ) : (
            <div className="mt-6 space-y-3 text-sm text-on-background/55">
              <div className="flex items-center justify-between">
                <span>会话恢复</span>
                <span className="font-mono text-primary-container/80">AUTH</span>
              </div>
              <div className="flex items-center justify-between">
                <span>服务健康检查</span>
                <span className="font-mono text-primary-container/80">HEALTH</span>
              </div>
              <div className="flex items-center justify-between">
                <span>地图与行政区划初始化</span>
                <span className="font-mono text-primary-container/80">MAP</span>
              </div>
            </div>
          )}
        </motion.div>
      </section>
    </motion.div>
  );
}
