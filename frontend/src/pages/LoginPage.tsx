import { useRef, useState } from 'react';
import { AxiosError } from 'axios';
import gsap from 'gsap';
import { useGSAP } from '@gsap/react';
import { ArrowRight, LockKeyhole, ShieldCheck, UserRound } from 'lucide-react';
import { Navigate, useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthProvider';
import { glassLightStyle, glassStyle } from '../lib/glass';
import { useResolvedTheme } from '../lib/theme';
import { cn } from '../lib/utils';

gsap.registerPlugin(useGSAP);

type LoginMotionConditions = {
  isDesktop?: boolean;
  reduceMotion?: boolean;
};

type AmbientOrbitLight = {
  element: HTMLElement;
  phase: number;
  baseAlpha: number;
  alphaPulse: number;
  scaleBase: number;
  scalePulse: number;
};

type LoginBackgroundTheme = {
  pageWash: string;
  gridBackgroundSize: string;
  gridAccentBackgroundSize: string;
  gridOpacity: number;
  gridFineLine: string;
  gridAccentLine: string;
  topAmbient: {
    opacity: number;
    background: string;
    baseAlpha: number;
    alphaPulse: number;
    scaleBase: number;
    scalePulse: number;
  };
  rightAmbient: {
    opacity: number;
    background: string;
    baseAlpha: number;
    alphaPulse: number;
    scaleBase: number;
    scalePulse: number;
  };
};

const LOGIN_BACKGROUND_THEME: Record<'light' | 'dark', LoginBackgroundTheme> = {
  light: {
    pageWash:
      'radial-gradient(circle at bottom right, rgba(28,28,33,0.085), transparent 24%), radial-gradient(circle at 12% 18%, rgba(240,112,64,0.08), transparent 32%)',
    gridBackgroundSize: '48px 48px',
    gridAccentBackgroundSize: '192px 192px',
    gridOpacity: 0.3,
    gridFineLine:
      'linear-gradient(rgba(28,28,33,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(28,28,33,0.1) 1px, transparent 1px)',
    gridAccentLine:
      'linear-gradient(rgba(240,112,64,0.09) 1px, transparent 1px), linear-gradient(90deg, rgba(240,112,64,0.09) 1px, transparent 1px)',
    topAmbient: {
      opacity: 0.74,
      background:
        'radial-gradient(circle, rgba(240,112,64,0.44), rgba(240,112,64,0.2) 38%, rgba(240,112,64,0.08) 58%, transparent 74%)',
      baseAlpha: 0.74,
      alphaPulse: 0.1,
      scaleBase: 1,
      scalePulse: 0.07,
    },
    rightAmbient: {
      opacity: 0.62,
      background:
        'radial-gradient(circle, rgba(240,112,64,0.2), rgba(232,168,124,0.1) 42%, rgba(240,112,64,0.045) 64%, transparent 82%)',
      baseAlpha: 0.62,
      alphaPulse: 0.08,
      scaleBase: 1.02,
      scalePulse: 0.06,
    },
  },
  dark: {
    pageWash:
      'radial-gradient(circle at bottom right, rgba(255,255,255,0.07), transparent 26%), radial-gradient(circle at 14% 18%, rgba(240,112,64,0.1), transparent 34%)',
    gridBackgroundSize: '48px 48px',
    gridAccentBackgroundSize: '192px 192px',
    gridOpacity: 0.4,
    gridFineLine:
      'linear-gradient(rgba(255,255,255,0.072) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.072) 1px, transparent 1px)',
    gridAccentLine:
      'linear-gradient(rgba(240,112,64,0.12) 1px, transparent 1px), linear-gradient(90deg, rgba(240,112,64,0.12) 1px, transparent 1px)',
    topAmbient: {
      opacity: 0.86,
      background:
        'radial-gradient(circle, rgba(240,112,64,0.46), rgba(240,112,64,0.2) 42%, rgba(240,112,64,0.09) 62%, transparent 76%)',
      baseAlpha: 0.86,
      alphaPulse: 0.1,
      scaleBase: 1,
      scalePulse: 0.07,
    },
    rightAmbient: {
      opacity: 0.72,
      background:
        'radial-gradient(circle, rgba(240,112,64,0.24), rgba(232,168,124,0.12) 42%, rgba(240,112,64,0.055) 66%, transparent 84%)',
      baseAlpha: 0.72,
      alphaPulse: 0.09,
      scaleBase: 1.02,
      scalePulse: 0.06,
    },
  },
};

function getErrorMessage(error: unknown): string {
  if (error instanceof AxiosError) {
    return (
      (typeof error.response?.data === 'object' &&
      error.response?.data &&
      'detail' in error.response.data
        ? String(error.response.data.detail)
        : undefined) || '登录失败，请检查账号和密码。'
    );
  }
  return '登录失败，请稍后重试。';
}

export default function LoginPage() {
  const rootRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const { login, startDemo, status } = useAuth();
  const theme = useResolvedTheme();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [demoSubmitting, setDemoSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isLight = theme === 'light';
  const backgroundTheme = LOGIN_BACKGROUND_THEME[theme];

  useGSAP(() => {
    const root = rootRef.current;
    if (!root) return;

    const mm = gsap.matchMedia();

    mm.add(
      {
        isDesktop: '(min-width: 1024px)',
        reduceMotion: '(prefers-reduced-motion: reduce)',
      },
      (context) => {
        const { isDesktop, reduceMotion } = (context.conditions ?? {}) as LoginMotionConditions;
        const introItems = gsap.utils.toArray<HTMLElement>('[data-login-intro]');
        const featureCards = gsap.utils.toArray<HTMLElement>('[data-login-feature]');
        const motionLayers = gsap.utils.toArray<HTMLElement>('[data-login-motion-layer]');
        const topAmbient = root.querySelector<HTMLElement>('[data-login-top-ambient]');
        const rightAmbient = root.querySelector<HTMLElement>('[data-login-right-ambient]');
        const gridLayer = root.querySelector<HTMLElement>('[data-login-grid]');
        const cardShell = root.querySelector<HTMLElement>('[data-login-card-shell]');
        const cardHalo = root.querySelector<HTMLElement>('[data-login-card-halo]');
        const brandHaloRing = root.querySelector<HTMLElement>('[data-login-brand-halo-ring]');
        const actionButtons = gsap.utils.toArray<HTMLElement>('[data-login-action]');
        const cleanup: Array<() => void> = [];

        gsap.set([...introItems, ...featureCards, ...motionLayers], {
          willChange: 'transform, opacity',
        });

        gsap.from(introItems, {
          autoAlpha: 0,
          y: reduceMotion ? 6 : 22,
          scale: reduceMotion ? 1 : 0.985,
          duration: reduceMotion ? 0.2 : 0.82,
          stagger: reduceMotion ? 0.03 : 0.08,
          ease: 'power3.out',
        });

        const ambientLights: AmbientOrbitLight[] = [
          ...(topAmbient
            ? [
                {
                  element: topAmbient,
                  phase: Math.PI * 1.25,
                  baseAlpha: backgroundTheme.topAmbient.baseAlpha,
                  alphaPulse: backgroundTheme.topAmbient.alphaPulse,
                  scaleBase: backgroundTheme.topAmbient.scaleBase,
                  scalePulse: backgroundTheme.topAmbient.scalePulse,
                },
              ]
            : []),
          ...(rightAmbient
            ? [
                {
                  element: rightAmbient,
                  phase: Math.PI * 0.25,
                  baseAlpha: backgroundTheme.rightAmbient.baseAlpha,
                  alphaPulse: backgroundTheme.rightAmbient.alphaPulse,
                  scaleBase: backgroundTheme.rightAmbient.scaleBase,
                  scalePulse: backgroundTheme.rightAmbient.scalePulse,
                },
              ]
            : []),
        ];

        if (ambientLights.length > 0) {
          const ambientElements = ambientLights.map((light) => light.element);
          let orbitWidth = root.clientWidth || window.innerWidth;
          let orbitHeight = root.clientHeight || window.innerHeight;

          const refreshOrbitMetrics = () => {
            const bounds = root.getBoundingClientRect();
            orbitWidth = bounds.width || window.innerWidth;
            orbitHeight = bounds.height || window.innerHeight;
          };

          const placeAmbientLights = (t = 0) => {
            const radiusX = Math.max(orbitWidth * 0.58, 360);
            const radiusY = Math.max(orbitHeight * 0.52, 280);
            const angle =
              t * 0.22 +
              Math.sin(t * 0.47) * 0.28 +
              Math.sin(t * 0.13) * 0.18;

            ambientLights.forEach((light) => {
              const orbitAngle = angle + light.phase;
              const pulse = Math.sin(t * 0.36 + light.phase);

              gsap.set(light.element, {
                x: Math.cos(orbitAngle) * radiusX,
                y: Math.sin(orbitAngle) * radiusY,
                scale: light.scaleBase + pulse * light.scalePulse,
                autoAlpha: light.baseAlpha + pulse * light.alphaPulse,
              });
            });
          };

          gsap.set(ambientElements, {
            xPercent: -50,
            yPercent: -50,
            willChange: 'transform, opacity',
          });

          refreshOrbitMetrics();
          placeAmbientLights(0);

          const handleResize = () => {
            refreshOrbitMetrics();
            placeAmbientLights(gsap.ticker.time);
          };

          window.addEventListener('resize', handleResize);
          cleanup.push(() => window.removeEventListener('resize', handleResize));

          if (!reduceMotion) {
            const updateAmbientOrbits = (time: number) => {
              placeAmbientLights(time);
            };

            gsap.ticker.add(updateAmbientOrbits);
            cleanup.push(() => gsap.ticker.remove(updateAmbientOrbits));
          }
        }

        if (reduceMotion) {
          return () => cleanup.forEach((dispose) => dispose());
        }

        if (gridLayer) {
          gsap.to(gridLayer, {
            x: 26,
            y: -18,
            duration: 18,
            repeat: -1,
            yoyo: true,
            ease: 'sine.inOut',
          });
        }

        if (brandHaloRing) {
          gsap.set(brandHaloRing, {
            transformOrigin: '50% 50%',
            willChange: 'transform, opacity',
          });
          gsap.to(brandHaloRing, {
            opacity: isLight ? 0.58 : 0.76,
            scale: 1.14,
            duration: 2.8,
            repeat: -1,
            yoyo: true,
            ease: 'sine.inOut',
          });
        }

        if (cardHalo) {
          gsap.to(cardHalo, {
            autoAlpha: 0.88,
            scale: 1.012,
            duration: 3.4,
            repeat: -1,
            yoyo: true,
            ease: 'sine.inOut',
          });
        }

        if (featureCards.length > 0) {
          gsap.to(featureCards, {
            y: (index) => (index % 2 === 0 ? -4 : 4),
            duration: 4.2,
            repeat: -1,
            yoyo: true,
            stagger: 0.42,
            ease: 'sine.inOut',
          });
        }

        actionButtons.forEach((button) => {
          const arrow = button.querySelector<HTMLElement>('[data-login-action-arrow]');
          if (!arrow) return;

          const arrowXTo = gsap.quickTo(arrow, 'x', { duration: 0.34, ease: 'power3.out' });
          const buttonYTo = gsap.quickTo(button, 'y', { duration: 0.34, ease: 'power3.out' });
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
          });
        });

        if (isDesktop && cardShell) {
          gsap.set(cardShell, { transformPerspective: 1200, transformOrigin: '50% 50%' });
          const rotateXTo = gsap.quickTo(cardShell, 'rotationX', { duration: 0.7, ease: 'power3.out' });
          const rotateYTo = gsap.quickTo(cardShell, 'rotationY', { duration: 0.7, ease: 'power3.out' });
          const cardYTo = gsap.quickTo(cardShell, 'y', { duration: 0.7, ease: 'power3.out' });

          const onPointerMove = (event: PointerEvent) => {
            const bounds = root.getBoundingClientRect();
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
          });
        }

        return () => cleanup.forEach((dispose) => dispose());
      },
      root
    );

    return () => mm.revert();
  }, { scope: rootRef });

  if (status === 'authenticated') {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login({ username: username.trim(), password });
      navigate('/', { replace: true });
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDemoAccess = async () => {
    setDemoSubmitting(true);
    setError(null);
    try {
      await startDemo();
      navigate('/', { replace: true });
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setDemoSubmitting(false);
    }
  };

  return (
    <div ref={rootRef} className="relative min-h-screen overflow-hidden bg-background text-on-background">
      <div
        data-login-motion-layer
        className="absolute inset-0"
        style={{
          background: backgroundTheme.pageWash,
        }}
      />
      <div
        data-login-motion-layer
        data-login-top-ambient
        className="pointer-events-none absolute left-1/2 top-1/2 h-[42vh] min-h-[320px] w-[42vw] min-w-[320px] rounded-full blur-3xl"
        style={{
          opacity: backgroundTheme.topAmbient.opacity,
          background: backgroundTheme.topAmbient.background,
        }}
      />
      <div
        data-login-motion-layer
        data-login-right-ambient
        className="pointer-events-none absolute left-1/2 top-1/2 h-[78vh] min-h-[520px] w-[58vw] min-w-[520px] rounded-full blur-3xl"
        style={{
          opacity: backgroundTheme.rightAmbient.opacity,
          background: backgroundTheme.rightAmbient.background,
        }}
      />
      <div
        data-login-motion-layer
        data-login-grid
        className="absolute inset-0"
        style={{
          opacity: backgroundTheme.gridOpacity,
          backgroundImage: `${backgroundTheme.gridFineLine}, ${backgroundTheme.gridAccentLine}`,
          backgroundSize: `${backgroundTheme.gridBackgroundSize}, ${backgroundTheme.gridBackgroundSize}, ${backgroundTheme.gridAccentBackgroundSize}, ${backgroundTheme.gridAccentBackgroundSize}`,
        }}
      />

      <main className="relative mx-auto flex min-h-screen max-w-7xl items-center justify-between gap-10 px-6 py-12">
        <section className="hidden max-w-2xl lg:block">
          <p data-login-intro className="text-sm font-semibold uppercase tracking-[0.3em] text-primary-container/70">
            Sentinel GeoAI
          </p>
          <h1 data-login-intro className="mt-6 font-headline text-6xl font-semibold leading-[1.05] text-on-background">
            标准规范
            <br />
            智能空间查询系统
          </h1>
          <p data-login-intro className="mt-6 max-w-xl text-lg leading-8 text-on-background/62">
            使用管理员会话进入统一检索与空间分析工作台。登录后即可访问知识检索、地图联动、文档详情与系统管理能力。
          </p>

          <div data-login-intro className="mt-10 grid max-w-xl gap-4">
            {[
              '统一安全入口，避免匿名暴露内部业务接口',
              '登录态自动恢复，刷新后继续当前工作流',
              '启动阶段先检查服务健康和地图核心数据，再进入主界面',
            ].map((item) => (
              <div
                key={item}
                data-login-feature
                className="glass-light rounded-2xl border border-outline/60 px-5 py-4 text-sm text-on-background/75"
                style={glassLightStyle}
              >
                {item}
              </div>
            ))}
          </div>
        </section>

        <section className="w-full max-w-md shrink-0 [perspective:1200px]">
          <div
            data-login-card-shell
            data-login-intro
            className="relative"
          >
            <div
              data-login-card-halo
              className="pointer-events-none absolute -inset-1 rounded-[30px] border border-primary-container/20 opacity-55"
            />
            <div
              className="glass relative rounded-[28px] border border-outline/60 px-7 py-8"
              style={{
                ...glassStyle,
                boxShadow: isLight
                  ? '0 24px 80px rgba(17, 24, 39, 0.12)'
                  : '0 24px 80px rgba(0,0,0,0.35)',
              }}
            >
            <div className="mb-8 flex items-center gap-4">
              <div data-login-brand-halo className="relative flex h-14 w-14 items-center justify-center rounded-2xl border border-primary-container/30 bg-primary-container/10 shadow-[0_0_24px_rgba(240,112,64,0.18)]">
                <div
                  data-login-brand-halo-ring
                  className="pointer-events-none absolute -inset-2 rounded-[22px] opacity-35 blur-sm"
                  style={{
                    background: isLight
                      ? 'radial-gradient(circle, rgba(240,112,64,0.18), transparent 62%)'
                      : 'radial-gradient(circle, rgba(240,112,64,0.28), transparent 64%)',
                    boxShadow: '0 0 28px rgba(240,112,64,0.22)',
                  }}
                />
                <ShieldCheck className="relative h-6 w-6 text-primary-container" />
              </div>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-primary-container/70">
                  Admin Access
                </p>
                <h2 className="mt-1 font-headline text-2xl font-semibold text-on-background">
                  管理员登录
                </h2>
              </div>
            </div>

            <form className="space-y-5" onSubmit={handleSubmit}>
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-on-background/70">账号</span>
                <div
                  className="flex items-center gap-3 rounded-2xl border border-outline/60 px-4 py-3 focus-within:border-primary-container/40"
                  style={{ background: isLight ? 'rgba(255,255,255,0.58)' : 'rgba(255,255,255,0.03)' }}
                >
                  <UserRound className="h-4 w-4 text-on-background/40" />
                  <input
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    autoComplete="username"
                    className="w-full bg-transparent text-sm text-on-background outline-none placeholder:text-on-background/25"
                    placeholder="请输入管理员账号"
                    required
                  />
                </div>
              </label>

              <label className="block">
                <span className="mb-2 block text-sm font-medium text-on-background/70">密码</span>
                <div
                  className="flex items-center gap-3 rounded-2xl border border-outline/60 px-4 py-3 focus-within:border-primary-container/40"
                  style={{ background: isLight ? 'rgba(255,255,255,0.58)' : 'rgba(255,255,255,0.03)' }}
                >
                  <LockKeyhole className="h-4 w-4 text-on-background/40" />
                  <input
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    type="password"
                    autoComplete="current-password"
                    className="w-full bg-transparent text-sm text-on-background outline-none placeholder:text-on-background/25"
                    placeholder="请输入登录密码"
                    required
                  />
                </div>
              </label>

              {error ? (
                <div
                  className={cn(
                    'rounded-2xl border px-4 py-3 text-sm',
                    isLight ? 'border-red-500/20 bg-red-500/8 text-red-700' : 'border-red-500/20 bg-red-500/8 text-red-200'
                  )}
                >
                  {error}
                </div>
              ) : null}

              <button
                type="submit"
                data-login-action
                disabled={submitting || demoSubmitting}
                className="flex w-full items-center justify-center gap-2 rounded-2xl bg-primary-container px-4 py-3 text-sm font-semibold text-on-primary-fixed transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-70"
              >
                <span>{submitting ? '正在验证身份' : '进入系统'}</span>
                <ArrowRight data-login-action-arrow className="h-4 w-4" />
              </button>
            </form>

            <div className="my-5 flex items-center gap-3">
              <div className="h-px flex-1 bg-outline/60" />
              <span className="text-xs font-medium text-on-background/45">公开演示</span>
              <div className="h-px flex-1 bg-outline/60" />
            </div>

            <button
              type="button"
              data-login-action
              onClick={handleDemoAccess}
              disabled={submitting || demoSubmitting}
              className="flex w-full items-center justify-center gap-2 rounded-2xl border border-primary-container/25 bg-primary-container/10 px-4 py-3 text-sm font-semibold text-primary-container transition hover:bg-primary-container/15 disabled:cursor-not-allowed disabled:opacity-70"
            >
              <span>{demoSubmitting ? '正在开启演示' : '访客体验'}</span>
              <ArrowRight data-login-action-arrow className="h-4 w-4" />
            </button>
            <p className="mt-3 text-center text-xs leading-5 text-on-background/45">
              访客无需注册，可体验检索、地图和有限次数的 AI 回答。
            </p>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
