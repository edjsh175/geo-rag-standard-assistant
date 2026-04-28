import { LoaderCircle, MapPinned, RefreshCcw } from 'lucide-react';

import { useResolvedTheme } from '../lib/theme';
import { cn } from '../lib/utils';

interface BootScreenProps {
  title?: string;
  status: string;
  detail?: string;
  error?: string | null;
  actionLabel?: string;
  onAction?: () => void;
  compact?: boolean;
}

export default function BootScreen({
  title = 'GeoAI 空间规划智能检索与可视化系统',
  status,
  detail,
  error,
  actionLabel = '重新尝试',
  onAction,
  compact = false,
}: BootScreenProps) {
  const theme = useResolvedTheme();
  const isLight = theme === 'light';

  return (
    <div
      className={cn(
        'absolute inset-0 z-[120] flex items-center justify-center overflow-hidden',
        compact ? 'bg-background/92 backdrop-blur-xl' : 'bg-background'
      )}
    >
      <div
        className="absolute inset-0"
        style={{
          background: isLight
            ? 'radial-gradient(circle at top, rgba(240,112,64,0.12), transparent 34%), radial-gradient(circle at bottom right, rgba(28,28,33,0.06), transparent 24%)'
            : 'radial-gradient(circle at top, rgba(240,112,64,0.18), transparent 35%), radial-gradient(circle at bottom right, rgba(255,255,255,0.08), transparent 28%)',
        }}
      />
      <div
        className="absolute inset-0 [background-size:48px_48px]"
        style={{
          opacity: isLight ? 0.16 : 0.3,
          backgroundImage: isLight
            ? 'linear-gradient(rgba(0,0,0,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.045) 1px, transparent 1px)'
            : 'linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)',
        }}
      />

      <section className="relative w-full max-w-xl px-6">
        <div
          className="glass rounded-[28px] border border-outline/60 px-8 py-10"
          style={{
            boxShadow: isLight
              ? '0 24px 80px rgba(17, 24, 39, 0.12)'
              : '0 24px 80px rgba(0,0,0,0.35)',
          }}
        >
          <div className="mb-8 flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-primary-container/30 bg-primary-container/10 shadow-[0_0_24px_rgba(240,112,64,0.18)]">
              <MapPinned className="h-6 w-6 text-primary-container" />
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
              <LoaderCircle
                className={cn(
                  'h-5 w-5 text-primary-container',
                  !error && 'animate-spin'
                )}
              />
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
        </div>
      </section>
    </div>
  );
}
