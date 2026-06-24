import { useRef } from 'react';
import { ArrowRight, CheckCircle2, LoaderCircle, MapPinned, RefreshCcw } from 'lucide-react';
import gsap from 'gsap';
import { useGSAP } from '@gsap/react';

import { glassStyle, glassLightStyle } from '../lib/glass';
import { useResolvedTheme } from '../lib/theme';
import { cn } from '../lib/utils';

gsap.registerPlugin(useGSAP);

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

type BootMotionConditions = {
  isDesktop?: boolean;
  reduceMotion?: boolean;
};

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
  const rootRef = useRef<HTMLDivElement>(null);
  const theme = useResolvedTheme();
  const isLight = theme === 'light';

  const isReady = phase === 'ready' && !error;
  const isEntering = phase === 'entering' && !error;

  useGSAP(
    () => {
      const root = rootRef.current;
      if (!root) return;

      const wash = root.querySelector<HTMLElement>('[data-boot-wash]');
      const grid = root.querySelector<HTMLElement>('[data-boot-grid]');
      const cardFloat = root.querySelector<HTMLElement>('[data-boot-card-float]');
      const cardShell = root.querySelector<HTMLElement>('[data-boot-card-shell]');
      const readyPanel = root.querySelector<HTMLElement>('[data-boot-ready-panel]');
      const brandHaloRing = root.querySelector<HTMLElement>('[data-boot-brand-halo-ring]');
      const readyCheck = root.querySelector<Element>('[data-boot-ready-check]');
      const actionButtons = Array.from(root.querySelectorAll<HTMLElement>('[data-boot-action]'));
      const animatedNodes = [
        root,
        wash,
        grid,
        cardFloat,
        cardShell,
        readyPanel,
        brandHaloRing,
        readyCheck,
      ].filter((node): node is Element => Boolean(node));

      const mm = gsap.matchMedia();

      mm.add(
        {
          isDesktop: '(min-width: 1024px)',
          reduceMotion: '(prefers-reduced-motion: reduce)',
        },
        (context) => {
          const { isDesktop = false, reduceMotion = false } =
            (context.conditions ?? {}) as BootMotionConditions;
          const overlayDuration = reduceMotion ? 0.24 : 0.9;
          const cardDuration = reduceMotion ? 0.2 : 0.72;
          const cleanup: Array<() => void> = [];

          gsap.set(animatedNodes, { willChange: 'transform, opacity, filter' });
          gsap.set(root, { autoAlpha: 1 });

          if (cardShell) {
            gsap.set(cardShell, {
              rotationX: 0,
              rotationY: 0,
              transformOrigin: '50% 50%',
              transformPerspective: 1200,
              y: 0,
            });
          }

          if (isEntering) {
            gsap.to(root, {
              autoAlpha: 0,
              duration: overlayDuration,
              ease: 'power3.out',
            });
            if (wash) {
              gsap.to(wash, {
                autoAlpha: reduceMotion ? 0.08 : 0,
                duration: overlayDuration,
                ease: 'power3.out',
                scale: reduceMotion ? 1.01 : 1.05,
              });
            }
            if (grid) {
              gsap.to(grid, {
                autoAlpha: 0,
                duration: overlayDuration,
                ease: 'power3.out',
              });
            }
            if (cardFloat) {
              gsap.to(cardFloat, {
                autoAlpha: 0,
                duration: cardDuration,
                ease: 'power3.out',
                filter: 'blur(10px)',
                scale: reduceMotion ? 0.99 : 0.965,
                y: reduceMotion ? -8 : -36,
              });
            }

            return () => {
              cleanup.forEach((fn) => fn());
              gsap.set(animatedNodes, { clearProps: 'willChange' });
            };
          }

          if (wash) {
            gsap.to(wash, {
              autoAlpha: 1,
              duration: overlayDuration,
              ease: 'power3.out',
              scale: 1,
            });
          }
          if (grid) {
            gsap.to(grid, {
              autoAlpha: isLight ? 0.16 : 0.3,
              duration: overlayDuration,
              ease: 'power3.out',
            });
          }
          if (cardFloat) {
            gsap.set(cardFloat, { filter: 'blur(0px)', y: 0 });
            gsap.to(cardFloat, {
              autoAlpha: 1,
              duration: cardDuration,
              ease: 'power3.out',
              scale: 1,
            });
          }

          if (brandHaloRing && !isReady) {
            gsap.set(brandHaloRing, {
              autoAlpha: isLight ? 0.32 : 0.42,
              scale: 1,
            });
          }

          if (!reduceMotion && !error && cardFloat) {
            gsap.to(cardFloat, {
              y: -4,
              duration: 4.2,
              repeat: -1,
              yoyo: true,
              ease: 'sine.inOut',
            });
          }

          if (isReady && readyPanel) {
            const readyTimeline = gsap.timeline({
              defaults: {
                duration: reduceMotion ? 0.18 : 0.52,
                ease: 'power3.out',
              },
            });

            readyTimeline.fromTo(
              readyPanel,
              { autoAlpha: 0, y: 10, scale: 0.985 },
              { autoAlpha: 1, y: 0, scale: 1 },
              0
            );

            if (readyCheck) {
              readyTimeline.fromTo(
                readyCheck,
                { autoAlpha: 0.72, scale: 0.86 },
                {
                  autoAlpha: 1,
                  duration: reduceMotion ? 0.18 : 0.42,
                  ease: 'back.out(1.7)',
                  scale: 1,
                },
                '<0.04'
              );
            }

            if (brandHaloRing) {
              readyTimeline
                .fromTo(
                  brandHaloRing,
                  { autoAlpha: isLight ? 0.34 : 0.46, scale: 0.92 },
                  {
                    autoAlpha: isLight ? 0.58 : 0.76,
                    duration: reduceMotion ? 0.18 : 0.72,
                    ease: 'sine.inOut',
                    scale: 1.14,
                  },
                  '<0.08'
                )
                .to(
                  brandHaloRing,
                  {
                    autoAlpha: isLight ? 0.42 : 0.56,
                    duration: reduceMotion ? 0.12 : 0.32,
                    ease: 'power2.out',
                    scale: 1,
                  },
                  '>'
                );
            }
          }

          if (isDesktop && !reduceMotion && !error && cardShell) {
            const rotateXTo = gsap.quickTo(cardShell, 'rotationX', { duration: 0.7, ease: 'power3.out' });
            const rotateYTo = gsap.quickTo(cardShell, 'rotationY', { duration: 0.7, ease: 'power3.out' });
            const cardYTo = gsap.quickTo(cardShell, 'y', { duration: 0.7, ease: 'power3.out' });

            const onPointerMove = (event: PointerEvent) => {
              const bounds = root.getBoundingClientRect();
              if (!bounds.width || !bounds.height) return;

              const relativeX = event.clientX - bounds.left;
              const relativeY = event.clientY - bounds.top;
              const centeredX = relativeX / bounds.width - 0.5;
              const centeredY = relativeY / bounds.height - 0.5;

              rotateXTo(centeredY * -10.5);
              rotateYTo(centeredX * 12.75);
              cardYTo(centeredY * 12);
            };

            const onPointerLeave = () => {
              rotateXTo(0);
              rotateYTo(0);
              cardYTo(0);
            };

            root.addEventListener('pointermove', onPointerMove);
            root.addEventListener('pointerleave', onPointerLeave);
            cleanup.push(() => {
              root.removeEventListener('pointermove', onPointerMove);
              root.removeEventListener('pointerleave', onPointerLeave);
              onPointerLeave();
            });
          }

          actionButtons.forEach((button) => {
            const arrow = button.querySelector<HTMLElement>('[data-boot-action-arrow]');
            if (!arrow) return;

            const arrowXTo = gsap.quickTo(arrow, 'x', {
              duration: reduceMotion ? 0.12 : 0.34,
              ease: 'power3.out',
            });
            const buttonYTo = gsap.quickTo(button, 'y', {
              duration: reduceMotion ? 0.12 : 0.34,
              ease: 'power3.out',
            });
            const onEnter = () => {
              arrowXTo(5);
              buttonYTo(-1);
            };
            const onLeave = () => {
              arrowXTo(0);
              buttonYTo(0);
            };

            button.addEventListener('pointerenter', onEnter);
            button.addEventListener('pointerleave', onLeave);
            cleanup.push(() => {
              button.removeEventListener('pointerenter', onEnter);
              button.removeEventListener('pointerleave', onLeave);
              onLeave();
            });
          });

          return () => {
            cleanup.forEach((fn) => fn());
            gsap.set(animatedNodes, { clearProps: 'willChange' });
          };
        },
        root
      );

      return () => {
        mm.revert();
      };
    },
    { scope: rootRef, dependencies: [phase, error, theme], revertOnUpdate: true }
  );

  return (
    <div
      ref={rootRef}
      data-boot-root
      className={cn(
        'absolute inset-0 z-[120] flex items-center justify-center overflow-hidden',
        compact ? 'bg-background/92 backdrop-blur-xl' : 'bg-background'
      )}
    >
      <div
        data-boot-wash
        className="absolute inset-0"
        style={{
          background: isLight
            ? 'radial-gradient(circle at top, rgba(240,112,64,0.12), transparent 34%), radial-gradient(circle at bottom right, rgba(28,28,33,0.06), transparent 24%)'
            : 'radial-gradient(circle at top, rgba(240,112,64,0.18), transparent 35%), radial-gradient(circle at bottom right, rgba(255,255,255,0.08), transparent 28%)',
        }}
      />

      <div
        data-boot-grid
        className="absolute inset-0 [background-size:48px_48px]"
        style={{
          backgroundImage: isLight
            ? 'linear-gradient(rgba(0,0,0,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.045) 1px, transparent 1px)'
            : 'linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)',
        }}
      />

      <section data-boot-card-float className="relative w-full max-w-xl px-6" style={{ perspective: '1200px' }}>
        <div
          data-boot-card-shell
          className="glass transform-gpu rounded-[28px] border border-outline/60 px-8 py-10"
          style={{
            ...glassStyle,
            boxShadow: isLight
              ? '0 24px 80px rgba(17, 24, 39, 0.12)'
              : '0 24px 80px rgba(0,0,0,0.35)',
          }}
        >
          <div className="mb-8 flex items-center gap-4">
            <div
              data-boot-brand-halo
              className="relative flex h-14 w-14 items-center justify-center rounded-2xl border border-primary-container/30 bg-primary-container/10 shadow-[0_0_24px_rgba(240,112,64,0.18)]"
            >
              <span
                data-boot-brand-halo-ring
                className="pointer-events-none absolute inset-[-8px] rounded-[26px]"
                style={{
                  background: 'radial-gradient(circle, rgba(240,112,64,0.22), transparent 68%)',
                }}
              />
              {isReady ? (
                <CheckCircle2 data-boot-ready-check className="relative z-10 h-6 w-6 text-primary-container" />
              ) : (
                <MapPinned className="relative z-10 h-6 w-6 text-primary-container" />
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
            style={{
              ...glassLightStyle,
              background: isLight ? 'rgba(255,255,255,0.58)' : 'rgba(255,255,255,0.03)',
            }}
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
            <div
              data-boot-ready-panel
              className="mt-6 transform-gpu rounded-[24px] border border-outline/50 px-5 py-5"
              style={{
                ...glassLightStyle,
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
                data-boot-action
                type="button"
                onClick={onPrimaryAction}
                className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-primary-container px-5 py-3.5 text-sm font-semibold text-on-primary-fixed transition hover:brightness-105"
              >
                <span>{primaryActionLabel}</span>
                <ArrowRight data-boot-action-arrow className="h-4 w-4" />
              </button>
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
