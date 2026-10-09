import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Layers,
  ArrowLeft,
  X,
  Download,
  FileText,
  RotateCcw,
  Bell,
  Radio,
  Settings,
  Sun,
  Moon,
  LogOut,
  Maximize2,
  Minimize2
} from 'lucide-react';
import { motion, AnimatePresence, useReducedMotion } from 'motion/react';
import CesiumGlobe from './components/CesiumGlobe';
import OpenLayersMap from './components/OpenLayersMap';
import BootScreen from './components/BootScreen';
import Chat from './components/Chat';
import { useAuth } from './auth/AuthProvider';
import { ensureBackendHealth, loadProvinceCollection, resetBootstrapCache } from './lib/bootstrap';
import { cn } from './lib/utils';
import { drawerGlassStyle, glassLightStyle, glassStyle } from './lib/glass';
import { useMapViewerState } from './hooks/useMapViewerState';
import { useAgentSession, resolveFollowUpContext } from './hooks/useAgentSession';
import { useDocumentManager, isIndexedStatus, indexingStatusLabel } from './hooks/useDocumentManager';

export { resolveFollowUpContext };

type BootCeremonyStage = 'loading' | 'ready' | 'entering' | 'done';

const getBootErrorMessage = (error: unknown): string => {
  if (error instanceof Error) {
    return error.message;
  }
  return '系统初始化失败，请稍后重试。';
};

export default function App() {
  const { logout, user, updateQuota } = useAuth();
  const isVisitor = user?.role === 'visitor';
  const reduceMotion = useReducedMotion();

  // ==================== 1. 主题管理 ====================
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');

  // ==================== 2. 三大核心业务 Hooks ====================
  const map = useMapViewerState();
  const doc = useDocumentManager();
  const { selectedDocument, isDrawerOpen, setIsDrawerOpen } = doc;

  // Authority invariant: Browser/UI-observed map state is authoritative.
  // Natural-language text must not mutate map facts before Controller interpretation.
  const activeRegion = map.activeRegion;
  const regionContext = activeRegion;

  const handleDocumentsFound = useCallback((documents: any[]) => {
    const newSearchResults = documents.map((d) => ({
      id: d.id,
      score: 0.8,
      document: d,
      highlights: {},
      explanation: '来自聊天上下文',
    }));
    doc.setSearchResults((prev) => [...prev, ...newSearchResults]);
  }, [doc]);

  const session = useAgentSession({
    user,
    updateQuota,
    activeRegion: map.activeRegion,
    setActiveRegion: map.setActiveRegion,
    selectedDocument: doc.selectedDocument,
    onDocumentsFound: handleDocumentsFound,
  });

  // ==================== 3. 引导开屏状态 ====================
  const [bootStatus, setBootStatus] = useState('正在检查服务健康状态');
  const [bootDetail, setBootDetail] = useState('请稍候，系统正在恢复安全会话与地图核心资源。');
  const [bootError, setBootError] = useState<string | null>(null);
  const [bootBaseReady, setBootBaseReady] = useState(false);
  const [bootRetryKey, setBootRetryKey] = useState(0);
  const [bootStage, setBootStage] = useState<BootCeremonyStage>('loading');
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const enterCeremonyTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const initialTheme = mediaQuery.matches ? 'dark' : 'light';
    setTheme(initialTheme);
    document.documentElement.dataset.theme = initialTheme;

    const handler = (e: MediaQueryListEvent) => {
      const newTheme = e.matches ? 'dark' : 'light';
      setTheme(newTheme);
      document.documentElement.dataset.theme = newTheme;
    };
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  const handleThemeChange = (newTheme: 'dark' | 'light') => {
    setTheme(newTheme);
    document.documentElement.dataset.theme = newTheme;
    if (newTheme === 'light' && map.layers.wms) {
      map.setLayers((prev) => ({ ...prev, wms: false }));
    }
  };

  const retryBoot = useCallback(() => {
    if (enterCeremonyTimerRef.current) {
      window.clearTimeout(enterCeremonyTimerRef.current);
      enterCeremonyTimerRef.current = null;
    }
    resetBootstrapCache();
    setBootError(null);
    setBootBaseReady(false);
    setBootStage('loading');
    setBootRetryKey((prev) => prev + 1);
  }, []);

  const handleEnterSystem = useCallback(() => {
    if (bootStage !== 'ready') return;

    setBootStage('entering');
    setBootStatus('正在展开主控界面');
    setBootDetail('地图已就绪，正在唤醒控制台与检索工作台。');

    if (enterCeremonyTimerRef.current) {
      window.clearTimeout(enterCeremonyTimerRef.current);
    }

    enterCeremonyTimerRef.current = window.setTimeout(() => {
      setBootStage('done');
      enterCeremonyTimerRef.current = null;
    }, reduceMotion ? 260 : 1280);
  }, [bootStage, reduceMotion]);

  const handleLogout = useCallback(async () => {
    if (isLoggingOut) return;
    setIsLoggingOut(true);
    try {
      await logout();
    } finally {
      setIsLoggingOut(false);
    }
  }, [isLoggingOut, logout]);

  useEffect(() => {
    let cancelled = false;

    const runBootSequence = async () => {
      try {
        setBootError(null);
        setBootBaseReady(false);
        setBootStatus('正在检查服务健康状态');
        setBootDetail('正在确认核心接口与数据服务可用性。');
        await ensureBackendHealth();
        if (cancelled) return;

        setBootStatus('正在预加载行政区划数据');
        setBootDetail('正在准备首屏地图所需的核心行政区划资源。');
        await loadProvinceCollection();
        if (cancelled) return;

        setBootBaseReady(true);
        setBootStatus(map.viewMode === '3D' ? '正在准备三维地图引擎' : '正在准备二维地图引擎');
        setBootDetail('地图引擎初始化完成后将自动进入主界面。');
      } catch (error) {
        if (cancelled) return;
        setBootError(getBootErrorMessage(error));
      }
    };

    runBootSequence();

    return () => {
      cancelled = true;
    };
  }, [bootRetryKey, map.viewMode]);

  useEffect(() => {
    if (bootError || !bootBaseReady || !map.mapReady[map.viewMode] || bootStage !== 'loading') return;

    setBootStage('ready');
    setBootStatus('系统准备就绪');
    setBootDetail('地图与核心资源已完成加载，点击一次进入系统。');
  }, [bootBaseReady, bootError, bootStage, map.mapReady, map.viewMode]);

  useEffect(() => {
    return () => {
      if (enterCeremonyTimerRef.current) {
        window.clearTimeout(enterCeremonyTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!bootBaseReady || bootError || bootStage !== 'loading') return;
    setBootStatus(map.viewMode === '3D' ? '正在准备三维地图视图' : '正在准备二维地图视图');
    setBootDetail('正在完成首屏地图初始化，请稍候。');
  }, [bootBaseReady, bootError, bootStage, map.viewMode]);

  const showBootOverlay = !!bootError || bootStage !== 'done';
  const uiVisible = bootStage === 'entering' || bootStage === 'done';
  const uiInteractive = bootStage === 'done';
  const bootPhase = bootError
    ? 'loading'
    : bootStage === 'ready'
      ? 'ready'
      : bootStage === 'entering'
        ? 'entering'
        : 'loading';

  const getLayerTransition = (delay: number) =>
    reduceMotion
      ? { duration: 0.2, delay: Math.min(delay, 0.08), ease: 'easeOut' as const }
      : { type: 'spring' as const, damping: 24, stiffness: 210, mass: 0.92, delay };

  const chatPanelTransition = reduceMotion
    ? { duration: 0.2, delay: bootStage === 'done' ? 0 : 0.08, ease: 'easeOut' as const }
    : {
        type: 'spring' as const,
        damping: 25,
        stiffness: 210,
        mass: 0.9,
        delay: bootStage === 'done' ? 0 : 0.66,
      };

  return (
    <div className="relative w-full h-screen text-on-background font-sans overflow-hidden" style={{ background: 'var(--color-background)' }}>
      {/* Background Map Layer */}
      <motion.section
        className="absolute inset-0 z-0 overflow-hidden"
        initial={false}
        animate={{
          opacity: bootStage === 'loading' ? 0.7 : bootStage === 'ready' ? 0.86 : 1,
          scale: uiVisible ? 1 : reduceMotion ? 1.01 : 1.045,
          filter: uiVisible
            ? 'blur(0px) saturate(1) brightness(1)'
            : reduceMotion
              ? 'blur(2px) saturate(0.92) brightness(0.88)'
              : 'blur(12px) saturate(0.82) brightness(0.72)',
        }}
        transition={
          reduceMotion
            ? { duration: 0.28, ease: 'easeOut' }
            : { duration: 1.05, ease: [0.22, 1, 0.36, 1] }
        }
        style={{ background: '#08080b', pointerEvents: uiInteractive ? 'auto' : 'none' }}
      >
        <CesiumGlobe
          theme={theme}
          visible={map.viewMode === '3D'}
          layoutMode={map.mapLayoutMode}
          viewportWidth={map.viewportWidth}
          layers={map.layers}
          onReady={map.handleMapReady3D}
          onAgentLayerVisibilityChange={map.handleAgentLayerVisibilityChange}
        />
        <OpenLayersMap
          theme={theme}
          visible={map.viewMode === '2D'}
          layoutMode={map.mapLayoutMode}
          viewportWidth={map.viewportWidth}
          layers={map.layers}
          onReady={map.handleMapReady2D}
          onAgentLayerVisibilityChange={map.handleAgentLayerVisibilityChange}
        />
      </motion.section>

      {showBootOverlay ? (
        <BootScreen
          compact
          phase={bootPhase}
          status={bootStatus}
          detail={bootDetail}
          error={bootError}
          onAction={bootError ? retryBoot : undefined}
          onPrimaryAction={bootError ? undefined : handleEnterSystem}
          primaryActionLabel="进入系统"
        />
      ) : null}

      {/* Floating Header */}
      <motion.header
        className={cn(
          "fixed top-4 left-4 right-4 z-50 glass h-[48px] rounded-2xl flex items-center justify-between px-6",
          uiInteractive ? 'pointer-events-auto' : 'pointer-events-none'
        )}
        initial={false}
        animate={{
          opacity: uiVisible ? 1 : 0,
          y: uiVisible ? 0 : reduceMotion ? -6 : -30,
          filter: uiVisible ? 'blur(0px)' : 'blur(12px)',
        }}
        transition={getLayerTransition(reduceMotion ? 0.03 : 0.28)}
        style={{ ...glassStyle, border: '0.5px solid var(--color-outline)', boxShadow: '0 8px 32px rgba(0,0,0,0.1)' }}
      >
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2.5 font-headline">
            <div className="relative w-5 h-5">
              <div className="absolute inset-0 rotate-45 rounded-[3px]" style={{ background: '#f07040', boxShadow: '0 0 10px rgba(240,112,64,0.7)' }} />
              <div className="absolute inset-[3px] rotate-45 rounded-[1px]" style={{ background: 'var(--color-background)' }} />
            </div>
            <span className="text-sm font-semibold tracking-wide text-on-background/90">标准规范</span>
            <span className="text-sm font-light text-on-background/20">·</span>
            <span className="text-sm font-light text-on-background/45">智能空间查询系统</span>
          </div>
          <nav className="flex items-center h-[48px] ml-2 gap-1">
            <a className="nav-active text-xs font-medium h-full flex items-center px-4 transition-all" href="#">检索</a>
            <a className="text-xs font-medium h-full flex items-center px-4 transition-colors text-on-background/35 hover:text-on-background/70" href="/crawler/">知识库</a>
            {!isVisitor && (
              <a className="text-xs font-medium h-full flex items-center px-4 transition-colors text-on-background/35 hover:text-on-background/70" href="#">系统管理</a>
            )}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full" style={{ background: 'rgba(16,185,129,0.08)', border: '0.5px solid rgba(16,185,129,0.2)' }}>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-soft" style={{ boxShadow: '0 0 6px rgba(16,185,129,0.7)' }}></span>
            <span className="text-[12.5px] font-medium" style={{ color: 'rgba(16,185,129,0.8)' }}>已连接</span>
          </div>
          <div className="flex gap-1.5 items-center mr-2">
            <div className="flex bg-on-background/5 p-0.5 rounded-lg border border-on-background/10 mr-2">
              <button 
                onClick={() => handleThemeChange('light')}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1 rounded-md text-[12.5px] font-semibold transition-all",
                  theme === 'light' ? "bg-white text-black shadow-sm" : "text-on-background/40 hover:text-on-background/70"
                )}
              >
                <Sun className="w-3 h-3" /> 日间
              </button>
              <button 
                onClick={() => handleThemeChange('dark')}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1 rounded-md text-[12.5px] font-semibold transition-all",
                  theme === 'dark' ? "bg-white/10 text-white shadow-sm" : "text-on-background/40 hover:text-on-background/70"
                )}
              >
                <Moon className="w-3 h-3" /> 夜间
              </button>
            </div>

            <button className="w-7 h-7 rounded-lg flex items-center justify-center transition-all bg-on-background/5 hover:bg-on-background/10 border border-on-background/5"><Radio className="w-3.5 h-3.5 text-on-background/40" /></button>
            <button className="w-7 h-7 rounded-lg flex items-center justify-center transition-all relative bg-on-background/5 hover:bg-on-background/10 border border-on-background/5"><Bell className="w-3.5 h-3.5 text-on-background/40" /><span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-orange-400 shadow-orange-glow" /></button>
            <button className="w-7 h-7 rounded-lg flex items-center justify-center transition-all bg-on-background/5 hover:bg-on-background/10 border border-on-background/5"><Settings className="w-3.5 h-3.5 text-on-background/40" /></button>
          </div>
          <button
            onClick={handleLogout}
            disabled={isLoggingOut}
            className="ml-1 inline-flex items-center gap-2 rounded-full border border-on-background/10 bg-on-background/5 px-2 py-1 text-[12px] font-semibold text-on-background/70 transition hover:bg-on-background/10 disabled:opacity-60"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-container/15 text-primary-container">
              {(user?.username?.slice(0, 1) || 'A').toUpperCase()}
            </span>
            <span className="hidden sm:inline">{isLoggingOut ? '退出中' : '退出登录'}</span>
            <LogOut className="h-3.5 w-3.5" />
          </button>
        </div>
      </motion.header>

      {/* Floating Overlay Controls / Content */}
      <main className="absolute inset-0 pointer-events-none z-10">
        {/* Layer Controls - Bottom Left */}
        <motion.div
          className={cn(
            "absolute bottom-16 left-6 z-10",
            uiInteractive ? 'pointer-events-auto' : 'pointer-events-none'
          )}
          initial={false}
          animate={{
            opacity: uiVisible ? 1 : 0,
            x: uiVisible ? 0 : reduceMotion ? -6 : -34,
            y: uiVisible ? 0 : reduceMotion ? 6 : 22,
          }}
          transition={getLayerTransition(reduceMotion ? 0.05 : 0.42)}
        >
          <div className="glass-light p-4 rounded-xl flex flex-col gap-3.5" style={{ ...glassLightStyle, minWidth: '168px', border: '0.5px solid var(--color-outline)', boxShadow: '0 8px 32px rgba(0,0,0,0.1)' }}>
            <div className="flex items-center gap-1.5 mb-0.5">
              <Layers className="w-3 h-3" style={{ color: 'rgba(240,112,64,0.7)' }} />
              <span className="text-[11.5px] font-semibold uppercase tracking-[0.15em]" style={{ color: 'rgba(240,112,64,0.65)' }}>图层控制</span>
            </div>
            {[
              { id: 'admin', label: '行政区划' },
              { id: 'wms', label: '卫星底图' }
            ].map((layer) => {
              const isOn = map.layers[layer.id as keyof typeof map.layers];
              return (
                <div key={layer.id} className="flex items-center justify-between gap-4">
                  <span className={cn("text-[13.5px] font-medium transition-colors", isOn ? "text-on-background/80" : "text-on-background/35")}>{layer.label}</span>
                  <div className={`toggle-track ${isOn ? 'on' : 'off'}`} onClick={() => map.toggleLayer(layer.id as keyof typeof map.layers)}>
                    <motion.div
                      className={`toggle-thumb ${isOn ? 'on' : 'off'}`}
                      animate={{ x: isOn ? 17 : 3 }}
                      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </motion.div>

        {/* Info Badge - Top Left (below header) */}
        <motion.div
          className={cn(
            "absolute top-[80px] left-5 z-10",
            uiInteractive ? 'pointer-events-auto' : 'pointer-events-none'
          )}
          initial={false}
          animate={{
            opacity: uiVisible ? 1 : 0,
            x: uiVisible ? 0 : reduceMotion ? -6 : -28,
            y: uiVisible ? 0 : reduceMotion ? 4 : 10,
          }}
          transition={getLayerTransition(reduceMotion ? 0.06 : 0.36)}
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={map.activeRegion?.adcode ?? 'overview'}
              initial={{ opacity: 0, x: -6, scale: 0.97 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 6, scale: 0.97 }}
              transition={{ duration: 0.2 }}
              className="glass-light flex flex-col items-start px-4 py-3 rounded-xl"
              style={{ ...glassLightStyle, border: '0.5px solid var(--color-outline-glow)', boxShadow: '0 0 24px rgba(0,0,0,0.1)' }}
            >
              {map.activeRegion ? (
                <>
                  <span className="font-headline font-bold text-xl tracking-tight text-glow" style={{ color: 'var(--color-primary)' }}>{map.activeRegion.name}</span>
                  <span className="font-mono text-[11.5px] tracking-[0.18em] mt-0.5" style={{ color: 'var(--color-primary-container)', opacity: 0.6 }}>ADCODE · {map.activeRegion.adcode}</span>
                </>
              ) : (
                <>
                  <span className="font-headline font-bold text-xl tracking-tight text-on-background/70">中国全貌</span>
                  <span className="font-mono text-[11.5px] tracking-[0.18em] mt-0.5 text-on-background/20">OVERVIEW</span>
                </>
              )}
            </motion.div>
          </AnimatePresence>
        </motion.div>

        {/* Mode Switcher - Bottom Center */}
        <motion.div
          className={cn(
            "absolute bottom-5 left-1/2 -translate-x-1/2 z-10",
            uiInteractive ? 'pointer-events-auto' : 'pointer-events-none'
          )}
          initial={false}
          animate={{
            opacity: uiVisible ? 1 : 0,
            y: uiVisible ? 0 : reduceMotion ? 6 : 26,
          }}
          transition={getLayerTransition(reduceMotion ? 0.07 : 0.54)}
        >
          <div className="glass p-[3px] rounded-full flex shadow-xl" style={{ ...glassStyle, border: '0.5px solid var(--color-outline)', boxShadow: '0 8px 32px rgba(0,0,0,0.1)' }}>
            {(['3D 地球', '2D 地图'] as const).map((label, i) => {
              const mode = i === 0 ? '3D' : '2D';
              const active = map.viewMode === mode;
              return (
                <button
                  key={mode}
                  onClick={() => map.handleViewModeSwitch(mode)}
                  className={cn("px-5 py-1.5 rounded-full text-xs font-semibold transition-all", !active && "text-on-background/35 hover:text-on-background/60")}
                  style={active ? { background: 'var(--color-primary-container)', color: 'var(--color-on-primary-fixed)', boxShadow: '0 0 12px var(--color-primary-glow)' } : {}}
                >{label}</button>
              );
            })}
          </div>
        </motion.div>

        {/* AI Chat Panel - Floating Right */}
        <motion.div
          className={cn(
            "absolute top-[80px] bottom-6 right-6 z-20",
            uiInteractive ? 'pointer-events-auto' : 'pointer-events-none'
          )}
          initial={false}
          animate={{
            opacity: uiVisible ? 1 : 0,
            width: map.chatPanelWidth,
            x: uiVisible ? 0 : reduceMotion ? 10 : 42,
            y: uiVisible ? 0 : reduceMotion ? 6 : 18,
            scale: uiVisible ? 1 : reduceMotion ? 0.995 : 0.975,
          }}
          transition={chatPanelTransition}
        >
          <div className="h-full rounded-2xl overflow-hidden glass border border-outline shadow-xl" style={glassStyle}>
            <Chat
              messages={session.messages}
              onSendMessage={session.handleChatSubmit}
              onVectorFilesSelected={session.handleVectorFilesSelected}
              reviewerEnabled={session.reviewerEnabled}
              onReviewerEnabledChange={session.setReviewerEnabled}
              sessions={session.agentSessions}
              activeSessionId={session.activeSessionId}
              sessionLoading={session.isHistoryRestoring}
              onRefreshSessions={session.refreshAgentSessions}
              onCreateSession={session.handleCreateAgentSession}
              onSelectSession={session.selectAgentSession}
              onDeleteSession={session.handleDeleteAgentSession}
              panelWidth={map.chatPanelWidth}
              isLoading={session.isChatLoading}
              activeTurn={session.activeTurn}
              onStopGeneration={session.handleStopGeneration}
              inputValue={session.chatInput}
              onInputChange={session.setChatInput}
              onCitationClick={doc.handleCitationClick}
              disabled={doc.isSearching || session.isHistoryRestoring || session.historyRestoreError}
              headerAction={
                <div className="flex items-center gap-2">
                  {session.historyRestoreError && (
                    <button
                      type="button"
                      onClick={session.retryHistoryRestore}
                      className="text-[10px] px-2 py-1 rounded-md bg-surface-variant/60 hover:bg-surface-variant border border-outline text-on-background"
                    >重试恢复</button>
                  )}
                  <motion.button
                    type="button"
                    aria-label={map.chatExpanded ? '收起对话框' : '展开对话框'}
                    title={map.chatExpanded ? '收起对话框' : '展开对话框'}
                    onClick={() => map.setChatExpanded((value) => !value)}
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.94 }}
                    className="w-7 h-7 rounded-lg flex items-center justify-center transition-all bg-surface-variant/40 hover:bg-surface-variant/70 border border-outline"
                  >
                    {map.chatExpanded ? (
                      <Minimize2 className="w-3.5 h-3.5 opacity-70 text-on-background" />
                    ) : (
                      <Maximize2 className="w-3.5 h-3.5 opacity-70 text-on-background" />
                    )}
                  </motion.button>
                </div>
              }
              title="Sentinel GeoAI"
              status={
                session.isHistoryRestoring
                  ? '正在恢复会话历史…'
                  : session.historyRestoreError
                    ? '会话恢复失败，请重试'
                    : user?.role === 'visitor'
                  ? user.quota?.exhausted
                    ? '访客模式 · AI 额度已用完'
                    : `访客模式 · AI 剩余 ${user.quota?.remaining ?? 0}/${user.quota?.daily_limit ?? 10}`
                  : '模型就绪 · RAG 已同步'
              }
              quickTags={['#城镇开发边界', '#永久基本农田', '#生态保护红线', '#四川技术规范']}
            />
          </div>
        </motion.div>

        {/* Coordinate Display */}
        <motion.div
          className="absolute bottom-5 left-1/2 -translate-x-1/2 -mb-12 z-10 flex items-center justify-center gap-3 font-mono text-[11.5px] text-on-background/30"
          initial={false}
          animate={{
            opacity: uiVisible ? 1 : 0,
            y: uiVisible ? 0 : reduceMotion ? 4 : 18,
          }}
          transition={getLayerTransition(reduceMotion ? 0.07 : 0.6)}
        >
          <span>LNG 104.0665</span>
          <span className="opacity-40">|</span>
          <span>LAT 30.5723</span>
          <span className="opacity-40">|</span>
          <span>ELE 500m</span>
          <span className="text-primary-container/40">WGS84</span>
        </motion.div>

        {/* Reset View */}
        <motion.div
          className={cn(
            "absolute bottom-[200px] left-6 z-10",
            uiInteractive ? 'pointer-events-auto' : 'pointer-events-none'
          )}
          initial={false}
          animate={{
            opacity: uiVisible ? 1 : 0,
            x: uiVisible ? 0 : reduceMotion ? -6 : -24,
            y: uiVisible ? 0 : reduceMotion ? 4 : 10,
          }}
          transition={getLayerTransition(reduceMotion ? 0.06 : 0.5)}
        >
          <motion.button
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
            onClick={map.resetView}
            className="glass-light flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium transition-all cursor-pointer"
            style={{ ...glassLightStyle, border: '0.5px solid var(--color-outline-glow)', color: 'var(--color-primary-container)', boxShadow: '0 8px 32px rgba(0,0,0,0.1)' }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(240,112,64,0.12)'; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = ''; }}
          >
            <RotateCcw className="w-3.5 h-3.5" />
            复位视角
          </motion.button>
        </motion.div>
      </main>

      {/* Details Drawer */}
      <AnimatePresence>
        {isDrawerOpen && selectedDocument && (
          <motion.section
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 220 }}
            className="fixed right-6 top-[80px] bottom-6 w-[420px] z-[60] flex flex-col"
            style={{ background: 'var(--glass-bg)', ...drawerGlassStyle, border: '0.5px solid var(--color-outline)', borderRadius: '1.5rem', boxShadow: '0 24px 64px rgba(0,0,0,0.3)' }}
          >
            {/* Details Drawer Header */}
            <div className="px-5 py-4 flex items-center justify-between shrink-0" style={{ borderBottom: '0.5px solid var(--color-outline)' }}>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setIsDrawerOpen(false)}
                  className="w-7 h-7 rounded-lg flex items-center justify-center transition-all bg-on-background/5 hover:bg-on-background/10 border border-on-background/5"
                >
                  <ArrowLeft className="w-3.5 h-3.5 text-on-background/40" />
                </button>
                <h3 className="text-sm font-semibold font-headline text-on-background/85">标准详情</h3>
              </div>
              <button
                onClick={() => setIsDrawerOpen(false)}
                className="w-7 h-7 rounded-lg flex items-center justify-center transition-all bg-on-background/5 hover:bg-on-background/10 border border-on-background/5"
              >
                <X className="w-3.5 h-3.5 text-on-background/35" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-8 space-y-10 no-scrollbar">
              <div className="space-y-4">
                <div className="flex items-center gap-4">
                  <div className="w-16 h-16 bg-primary-container/10 flex items-center justify-center rounded-2xl">
                    <FileText className="w-10 h-10 text-primary-container" />
                  </div>
                  <div>
                    <h2 className="text-xl font-extrabold text-on-background/90 leading-tight font-headline">{selectedDocument.metadata.title}</h2>
                    <p className="text-primary-container font-mono text-xs mt-1">{selectedDocument.id}</p>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 py-6 border-y border-outline-variant/10">
                  <div>
                    <p className="text-[12.5px] text-on-background/40 uppercase font-bold tracking-widest mb-1">文件类型</p>
                    <p className="text-sm text-on-background">{selectedDocument.file_type}</p>
                  </div>
                  <div>
                    <p className="text-[12.5px] text-on-background/40 uppercase font-bold tracking-widest mb-1">文件大小</p>
                    <p className="text-sm text-on-background">
                      {selectedDocument.file_size > 1024 * 1024
                        ? `${(selectedDocument.file_size / (1024 * 1024)).toFixed(2)} MB`
                        : `${(selectedDocument.file_size / 1024).toFixed(2)} KB`}
                    </p>
                  </div>
                  <div>
                    <p className="text-[12.5px] text-on-background/40 uppercase font-bold tracking-widest mb-1">上传时间</p>
                    <p className="text-sm text-on-background">
                      {new Date(selectedDocument.upload_time).toLocaleDateString('zh-CN')}
                    </p>
                  </div>
                  <div>
                    <p className="text-[12.5px] opacity-40 text-on-background uppercase font-bold tracking-widest mb-1">索引状态</p>
                    <span className={`px-2 py-0.5 rounded text-[12.5px] font-bold ${
                      isIndexedStatus(selectedDocument.indexing_status)
                        ? 'bg-emerald-500/15 text-emerald-500'
                        : selectedDocument.indexing_status === 'failed'
                        ? 'bg-red-500/15 text-red-500'
                        : 'bg-yellow-500/15 text-yellow-500'
                    }`}>
                      {indexingStatusLabel(selectedDocument.indexing_status)}
                    </span>
                  </div>
                </div>
              </div>

              {selectedDocument.spatial_metadata && (
                <div className="space-y-3">
                  <h4 className="text-xs font-bold text-[#90909a] uppercase tracking-widest">空间信息</h4>
                  <div className="grid grid-cols-2 gap-4">
                    {selectedDocument.spatial_metadata.city && (
                      <div>
                        <p className="text-[12.5px] text-on-background/40 uppercase font-bold tracking-widest mb-1">城市</p>
                        <p className="text-sm text-on-background">{selectedDocument.spatial_metadata.city}</p>
                      </div>
                    )}
                    {selectedDocument.spatial_metadata.province && (
                      <div>
                        <p className="text-[12.5px] text-on-background/40 uppercase font-bold tracking-widest mb-1">省份</p>
                        <p className="text-sm text-on-background">{selectedDocument.spatial_metadata.province}</p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="pt-8 mb-4">
                {selectedDocument.access_url ? (
                  <a
                    href={selectedDocument.access_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="w-full bg-surface-container-highest border border-outline-variant/30 py-4 rounded-xl text-on-background text-sm font-bold hover:bg-surface-bright transition-colors flex items-center justify-center gap-3"
                  >
                    <Download className="w-5 h-5 text-primary-container" /> 下载标准文档
                  </a>
                ) : (
                  <button className="w-full bg-surface-container-highest border border-outline-variant/30 py-4 rounded-xl text-on-background text-sm font-bold opacity-50 cursor-not-allowed flex items-center justify-center gap-3">
                    <Download className="w-5 h-5 text-primary-container" /> 文档锁定
                  </button>
                )}
              </div>
            </div>
          </motion.section>
        )}
      </AnimatePresence>
    </div>
  );
}
