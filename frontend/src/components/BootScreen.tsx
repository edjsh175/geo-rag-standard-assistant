import { LoaderCircle, MapPinned, RefreshCcw } from 'lucide-react';

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
  return (
    <div
      className={cn(
        'absolute inset-0 z-[120] flex items-center justify-center overflow-hidden',
        compact ? 'bg-background/92 backdrop-blur-xl' : 'bg-[#07070a]'
      )}
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(240,112,64,0.18),transparent_35%),radial-gradient(circle_at_bottom_right,rgba(255,255,255,0.08),transparent_28%)]" />
      <div className="absolute inset-0 opacity-30 [background-image:linear-gradient(rgba(255,255,255,0.04)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.04)_1px,transparent_1px)] [background-size:48px_48px]" />

      <section className="relative w-full max-w-xl px-6">
        <div className="glass rounded-[28px] border border-outline/60 px-8 py-10 shadow-[0_24px_80px_rgba(0,0,0,0.35)]">
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

          <div className="rounded-2xl border border-outline/50 bg-white/[0.03] px-5 py-4">
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
            <div className="mt-5 rounded-2xl border border-red-500/20 bg-red-500/8 px-5 py-4">
              <p className="text-sm font-medium text-red-200">{error}</p>
              {onAction ? (
                <button
                  type="button"
                  onClick={onAction}
                  className="mt-4 inline-flex items-center gap-2 rounded-full border border-red-400/25 bg-red-400/10 px-4 py-2 text-sm font-semibold text-red-100 transition hover:bg-red-400/16"
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
