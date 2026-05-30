import { useState } from 'react';
import { AxiosError } from 'axios';
import { ArrowRight, LockKeyhole, ShieldCheck, UserRound } from 'lucide-react';
import { Navigate, useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthProvider';
import { glassLightStyle, glassStyle } from '../lib/glass';
import { useResolvedTheme } from '../lib/theme';
import { cn } from '../lib/utils';

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
  const navigate = useNavigate();
  const { login, startDemo, status } = useAuth();
  const theme = useResolvedTheme();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [demoSubmitting, setDemoSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isLight = theme === 'light';

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
    <div className="relative min-h-screen overflow-hidden bg-background text-on-background">
      <div
        className="absolute inset-0"
        style={{
          background: isLight
            ? 'radial-gradient(circle at top left, rgba(240,112,64,0.14), transparent 28%), radial-gradient(circle at bottom right, rgba(28,28,33,0.08), transparent 22%)'
            : 'radial-gradient(circle at top left, rgba(240,112,64,0.22), transparent 28%), radial-gradient(circle at bottom right, rgba(255,255,255,0.08), transparent 24%)',
        }}
      />
      <div
        className="absolute inset-0 [background-size:52px_52px]"
        style={{
          opacity: isLight ? 0.16 : 0.3,
          backgroundImage: isLight
            ? 'linear-gradient(rgba(0,0,0,0.045) 1px,transparent 1px),linear-gradient(90deg,rgba(0,0,0,0.045) 1px,transparent 1px)'
            : 'linear-gradient(rgba(255,255,255,0.04) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.04) 1px,transparent 1px)',
        }}
      />

      <main className="relative mx-auto flex min-h-screen max-w-7xl items-center justify-between gap-10 px-6 py-12">
        <section className="hidden max-w-2xl lg:block">
          <p className="text-sm font-semibold uppercase tracking-[0.3em] text-primary-container/70">
            Sentinel GeoAI
          </p>
          <h1 className="mt-6 font-headline text-6xl font-semibold leading-[1.05] text-on-background">
            标准规范
            <br />
            智能空间查询系统
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-8 text-on-background/62">
            使用管理员会话进入统一检索与空间分析工作台。登录后即可访问知识检索、地图联动、文档详情与系统管理能力。
          </p>

          <div className="mt-10 grid max-w-xl gap-4">
            {[
              '统一安全入口，避免匿名暴露内部业务接口',
              '登录态自动恢复，刷新后继续当前工作流',
              '启动阶段先检查服务健康和地图核心数据，再进入主界面',
            ].map((item) => (
              <div
                key={item}
                className="glass-light rounded-2xl border border-outline/60 px-5 py-4 text-sm text-on-background/75"
                style={glassLightStyle}
              >
                {item}
              </div>
            ))}
          </div>
        </section>

        <section className="w-full max-w-md shrink-0">
          <div
            className="glass rounded-[28px] border border-outline/60 px-7 py-8"
            style={{
              ...glassStyle,
              boxShadow: isLight
                ? '0 24px 80px rgba(17, 24, 39, 0.12)'
                : '0 24px 80px rgba(0,0,0,0.35)',
            }}
          >
            <div className="mb-8 flex items-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-primary-container/30 bg-primary-container/10 shadow-[0_0_24px_rgba(240,112,64,0.18)]">
                <ShieldCheck className="h-6 w-6 text-primary-container" />
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
                disabled={submitting || demoSubmitting}
                className="flex w-full items-center justify-center gap-2 rounded-2xl bg-primary-container px-4 py-3 text-sm font-semibold text-on-primary-fixed transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-70"
              >
                <span>{submitting ? '正在验证身份' : '进入系统'}</span>
                <ArrowRight className="h-4 w-4" />
              </button>
            </form>

            <div className="my-5 flex items-center gap-3">
              <div className="h-px flex-1 bg-outline/60" />
              <span className="text-xs font-medium text-on-background/45">公开演示</span>
              <div className="h-px flex-1 bg-outline/60" />
            </div>

            <button
              type="button"
              onClick={handleDemoAccess}
              disabled={submitting || demoSubmitting}
              className="flex w-full items-center justify-center gap-2 rounded-2xl border border-primary-container/25 bg-primary-container/10 px-4 py-3 text-sm font-semibold text-primary-container transition hover:bg-primary-container/15 disabled:cursor-not-allowed disabled:opacity-70"
            >
              <span>{demoSubmitting ? '正在开启演示' : '访客体验'}</span>
              <ArrowRight className="h-4 w-4" />
            </button>
            <p className="mt-3 text-center text-xs leading-5 text-on-background/45">
              访客无需注册，可体验检索、地图和有限次数的 AI 回答。
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}
