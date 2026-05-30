import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  Map as MapIcon,
  Microscope,
  BarChart3,
  Settings,
  Layers,
  History,
  Bot,
  Sparkles,
  Mic,
  Send,
  ArrowLeft,
  X,
  Download,
  FileText,
  RotateCcw,
  Bell,
  Radio,
  Sun,
  Moon,
  LogOut
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
import { searchService } from './services/searchService';
import { chatService } from './services/chatService';
import { documentService } from './services/documentService';
import type {
  SearchResult,
  Document,
  ChatMessage as ChatMessageType,
  DocumentPreview,
  FollowUpContext,
  FollowUpCandidateDocument,
} from './types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useMapStore, zoomToHeight, heightToZoom } from './store/useMapStore';

const PROVINCE_MAP: Record<string, string> = {
  '110000': '北京市',
  '120000': '天津市',
  '130000': '河北省',
  '140000': '山西省',
  '150000': '内蒙古自治区',
  '210000': '辽宁省',
  '220000': '吉林省',
  '230000': '黑龙江省',
  '310000': '上海市',
  '320000': '江苏省',
  '330000': '浙江省',
  '340000': '安徽省',
  '350000': '福建省',
  '360000': '江西省',
  '370000': '山东省',
  '410000': '河南省',
  '420000': '湖北省',
  '430000': '湖南省',
  '440000': '广东省',
  '450000': '广西壮族自治区',
  '460000': '海南省',
  '500000': '重庆市',
  '510000': '四川省',
  '520000': '贵州省',
  '530000': '云南省',
  '540000': '西藏自治区',
  '610000': '陕西省',
  '620000': '甘肃省',
  '630000': '青海省',
  '640000': '宁夏回族自治区',
  '650000': '新疆维吾尔自治区',
  '710000': '台湾省',
  '810000': '香港特别行政区',
  '820000': '澳门特别行政区',
};

const buildRegionAliases = (name: string): string[] => {
  const compactName = name.replace(/\s+/g, '');
  const aliasSet = new Set([
    compactName,
    compactName.replace(/省$/, ''),
    compactName.replace(/市$/, ''),
    compactName.replace(/特别行政区$/, ''),
    compactName.replace(/壮族自治区$/, ''),
    compactName.replace(/回族自治区$/, ''),
    compactName.replace(/维吾尔自治区$/, ''),
    compactName.replace(/自治区$/, ''),
  ]);
  return Array.from(aliasSet).filter(Boolean);
};

const extractRegionFromQuery = (content: string): { adcode: string; name: string } | null => {
  const normalized = content.replace(/\s+/g, '');
  for (const [adcode, name] of Object.entries(PROVINCE_MAP)) {
    if (buildRegionAliases(name).some((alias) => normalized.includes(alias))) {
      return { adcode, name };
    }
  }
  return null;
};

const CURRENT_REGION_QUERY_PATTERN =
  /((当前|现在|刚才|我).*(选中|选择|点选|高亮).*(什么|哪里|哪个|区域|地区|省份|省))|((选中|选择|点选|高亮).*(什么|哪里|哪个|区域|地区|省份|省))|((当前|现在).*(什么|哪里|哪个).*(区域|地区|省份|省))|((当前|现在).*(区域|地区|省份|省).*(什么|哪里|哪个))/;

const REGION_REFERENCE_PATTERN =
  /(该地区|该区域|该省份|该省|该地|当地|本地区|这里|此处|当前区域|当前地区|当前省份|当前省|选中区域|选中地区|所选区域|所选地区|这个地区|这个区域|这个省份|这个省)/g;

const DOCUMENT_FOLLOW_UP_CUE_PATTERN =
  /(主要内容|讲了什么|主要讲|说了什么|核心要求|主要要求|适用范围|总结|概述|摘要|重点|介绍|解读|内容是什么)/;

const DOCUMENT_REFERENCE_PATTERN =
  /(这个标准|这个文档|这份文档|上面那个|上述标准|上述文档|该标准|该文档)/;

const ORDINAL_PATTERNS: Array<{ pattern: RegExp; rank: number | 'last' }> = [
  { pattern: /第(?:1|一)个/, rank: 1 },
  { pattern: /第(?:2|二)个/, rank: 2 },
  { pattern: /第(?:3|三)个/, rank: 3 },
  { pattern: /最后一个/, rank: 'last' },
];

const isCurrentRegionQuestion = (content: string): boolean =>
  CURRENT_REGION_QUERY_PATTERN.test(content.replace(/\s+/g, ''));

const buildRegionAwareQuery = (
  content: string,
  region: { adcode: string; name: string } | null
): string => {
  if (!region || extractRegionFromQuery(content)) {
    return content;
  }

  REGION_REFERENCE_PATTERN.lastIndex = 0;
  if (!REGION_REFERENCE_PATTERN.test(content)) {
    return content;
  }

  REGION_REFERENCE_PATTERN.lastIndex = 0;
  const expanded = content.replace(REGION_REFERENCE_PATTERN, region.name);
  return `${region.name} ${expanded}`;
};

const getLastAssistantCitations = (messages: ChatMessageType[]): FollowUpCandidateDocument[] => {
  const latestAssistantMessage = [...messages]
    .reverse()
    .find((message) => message.role === 'assistant' && (message.metadata?.citations?.length ?? 0) > 0);

  if (!latestAssistantMessage?.metadata?.citations) {
    return [];
  }

  const seen = new Set<string>();
  const candidates: FollowUpCandidateDocument[] = [];
  latestAssistantMessage.metadata.citations.forEach((citation, index) => {
    if (!citation.document_id || seen.has(citation.document_id)) {
      return;
    }
    seen.add(citation.document_id);
    candidates.push({
      id: citation.document_id,
      title: citation.title,
      rank: index + 1,
    });
  });
  return candidates;
};

const resolveFollowUpContext = (
  content: string,
  messages: ChatMessageType[],
  selectedDocument: Document | null
): FollowUpContext | undefined => {
  const compactContent = content.replace(/\s+/g, '');
  const candidates = getLastAssistantCitations(messages);
  const explicitIdMatch = compactContent.match(/\b(\d{4,})\b|(\d{4,})(?=的|讲|说|内容|标准|文档)/);
  const allKnownDocuments = [
    ...candidates,
    ...(selectedDocument
      ? [
          {
            id: selectedDocument.id,
            title: selectedDocument.metadata.title,
            rank: 0,
          },
        ]
      : []),
  ];

  const hasFollowUpCue =
    DOCUMENT_FOLLOW_UP_CUE_PATTERN.test(compactContent) || DOCUMENT_REFERENCE_PATTERN.test(compactContent);

  const explicitDocumentId = explicitIdMatch?.[1] || explicitIdMatch?.[2];
  if (explicitDocumentId && hasFollowUpCue) {
    return {
      target_document_id: explicitDocumentId,
      candidate_documents: candidates,
      resolution_source: 'explicit_text',
    };
  }

  const explicitDocument = allKnownDocuments.find((candidate) => compactContent.includes(candidate.id));
  if (explicitDocument && hasFollowUpCue) {
    return {
      target_document_id: explicitDocument.id,
      candidate_documents: candidates,
      resolution_source: 'explicit_text',
    };
  }

  for (const ordinalPattern of ORDINAL_PATTERNS) {
    if (!ordinalPattern.pattern.test(compactContent) || !hasFollowUpCue || candidates.length === 0) {
      continue;
    }

    const target =
      ordinalPattern.rank === 'last'
        ? candidates[candidates.length - 1]
        : candidates.find((candidate) => candidate.rank === ordinalPattern.rank);

    if (target) {
      return {
        target_document_id: target.id,
        candidate_documents: candidates,
        resolution_source: 'ordinal',
      };
    }
  }

  if (selectedDocument && DOCUMENT_REFERENCE_PATTERN.test(compactContent)) {
    return {
      target_document_id: selectedDocument.id,
      candidate_documents: candidates,
      resolution_source: 'selected_document',
    };
  }

  return undefined;
};

const getBootErrorMessage = (error: unknown): string => {
  if (error instanceof Error) {
    return error.message;
  }
  return '系统初始化失败，请稍后重试。';
};

type BootCeremonyStage = 'loading' | 'ready' | 'entering' | 'done';

export default function App() {
  const { logout, user, updateQuota } = useAuth();
  const isVisitor = user?.role === 'visitor';
  const reduceMotion = useReducedMotion();
  // ==================== 全局空间状态 ====================
  const viewMode = useMapStore((s) => s.viewMode);
  const setViewMode = useMapStore((s) => s.setViewMode);
  const activeRegion = useMapStore((s) => s.activeRegion);
  const setActiveRegion = useMapStore((s) => s.setActiveRegion);
  const setViewState = useMapStore((s) => s.setViewState);
  const resetView = useMapStore((s) => s.resetView);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [bootStatus, setBootStatus] = useState('正在检查服务健康状态');
  const [bootDetail, setBootDetail] = useState('请稍候，系统正在恢复安全会话与地图核心资源。');
  const [bootError, setBootError] = useState<string | null>(null);
  const [bootBaseReady, setBootBaseReady] = useState(false);
  const [bootRetryKey, setBootRetryKey] = useState(0);
  const [bootStage, setBootStage] = useState<BootCeremonyStage>('loading');
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [mapReady, setMapReady] = useState<{ '2D': boolean; '3D': boolean }>({
    '2D': false,
    '3D': false,
  });
  const enterCeremonyTimerRef = useRef<number | null>(null);

  // ==================== 主题管理 ====================
  useEffect(() => {
    // 1. 检测系统偏好
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const initialTheme = mediaQuery.matches ? 'dark' : 'light';
    setTheme(initialTheme);
    document.documentElement.dataset.theme = initialTheme;

    // 2. 监听系统偏好变化
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
    
    // 如果切换到日间模式，且当前是卫星图，则自动切换到电子底图以保持视觉一致
    if (newTheme === 'light' && layers.wms) {
      setLayers(prev => ({ ...prev, wms: false }));
    }
  };

  const markMapReady = useCallback((mode: '2D' | '3D') => {
    setMapReady((prev) => (prev[mode] ? prev : { ...prev, [mode]: true }));
  }, []);

  const handleMapReady2D = useCallback(() => {
    markMapReady('2D');
  }, [markMapReady]);

  const handleMapReady3D = useCallback(() => {
    markMapReady('3D');
  }, [markMapReady]);

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
        setBootStatus(viewMode === '3D' ? '正在准备三维地图引擎' : '正在准备二维地图引擎');
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
  }, [bootRetryKey]);

  useEffect(() => {
    if (bootError || !bootBaseReady || !mapReady[viewMode] || bootStage !== 'loading') return;

    setBootStage('ready');
    setBootStatus('系统准备就绪');
    setBootDetail('地图与核心资源已完成加载，点击一次进入系统。');
  }, [bootBaseReady, bootError, bootStage, mapReady, viewMode]);

  useEffect(() => {
    return () => {
      if (enterCeremonyTimerRef.current) {
        window.clearTimeout(enterCeremonyTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!bootBaseReady || bootError || bootStage !== 'loading') return;
    setBootStatus(viewMode === '3D' ? '正在准备三维地图视图' : '正在准备二维地图视图');
    setBootDetail('正在完成首屏地图初始化，请稍候。');
  }, [bootBaseReady, bootError, bootStage, viewMode]);

  // 2D/3D 地图容器 ref，用于视角交接
  const olContainerRef = useRef<HTMLDivElement>(null);
  const cesiumContainerRef = useRef<HTMLDivElement>(null);

  // ==================== "视角交接仪式" ====================
  // 切换引擎前：从当前引擎快照视角 → 写入 Store → 新引擎读取 Store 恢复
  const handleViewModeSwitch = useCallback((targetMode: '2D' | '3D') => {
    if (targetMode === viewMode) return;

    if (viewMode === '3D' && targetMode === '2D') {
      // 3D -> 2D: always snapshot the current Cesium view so post-focus pan/zoom survives mode switching.
      const cesiumEl = document.getElementById('cesiumContainer');
      if (cesiumEl && (cesiumEl as any).__snapshotView) {
        (cesiumEl as any).__snapshotView();
      }
      const { height, center } = useMapStore.getState().viewState;
      const zoom = heightToZoom(height, center[1]);
      setViewState({ zoom, center });
    } else {
      // 2D → 3D：读取 OL 视角，换算 height，写入 Store
      const olEl = olContainerRef.current?.querySelector('div[class]') ?? olContainerRef.current;
      // OpenLayersMap 把 __snapshotView 挂在自己的根 div 上
      // 我们需要找到 OpenLayersMap 渲染的那个 div
      const mapSection = document.querySelector('[data-ol-map]');
      if (mapSection && (mapSection as any).__snapshotView) {
        (mapSection as any).__snapshotView();
      } else {
        // fallback：遍历查找
        document.querySelectorAll('.w-full.h-full').forEach((el) => {
          if ((el as any).__snapshotView) (el as any).__snapshotView();
        });
      }
      const { zoom, center } = useMapStore.getState().viewState;
      const height = zoomToHeight(zoom, center[1]);
      setViewState({ height, center });
    }

    setViewMode(targetMode);
  }, [viewMode, setViewMode, setViewState]);
  const [layers, setLayers] = useState({
    admin: true,
    wms: false
  });
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [selectedStandard, setSelectedStandard] = useState<any>(null);

  // 聊天相关状态
  const [chatInput, setChatInput] = useState('');
  const [messages, setMessages] = useState<ChatMessageType[]>([
    {
      id: 'init-1',
      role: 'assistant',
      content: '您好！我是 **GeoAI 空间规划智能助手**。我已接入全面的空间规划文档库与地理空间数据库，可以为您提供便捷的专业智能检索服务。\n\n您可以尝试向我提出以下类型的问题：\n- **政策与标准检索**：例如*“请检索关于国土空间规划中城镇开发边界划定的技术标准”*\n- **空间定位协同**：例如*“定位到北京市”*\n- **规划文档查阅**：例如*“总结生态保护红线划定的基本原则”*\n\n请在下方输入框中输入您的指令或疑问，随时开始使用！',
      timestamp: new Date().toISOString(),
      metadata: {
        document_ids: [],
        citations: []
      }
    }
  ]);

  // 聊天加载状态
  const [isChatLoading, setIsChatLoading] = useState(false);
  // AbortController引用（用于中断请求）
  const abortControllerRef = useRef<AbortController | null>(null);

  const toggleLayer = (layer: keyof typeof layers) => {
    setLayers(prev => ({ ...prev, [layer]: !prev[layer] }));
  };

  // 搜索相关状态
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null);
  const [isLoadingDocument, setIsLoadingDocument] = useState(false);
  const [isDownloadingDocument, setIsDownloadingDocument] = useState(false);

  const handleReferenceClick = (doc: Document) => {
    setSelectedDocument(doc);
    setIsDrawerOpen(true);
  };

  // 搜索函数
  const handleSearch = async (query: string) => {
    if (!query.trim()) return;

    setIsSearching(true);
    try {
      // 使用快速搜索方法
      const documentResults = await searchService.quickSearch(query);

      // 将DocumentResult转换为SearchResult
      const results: SearchResult[] = documentResults.map(doc => ({
        id: doc.id,
        score: doc.similarity,
        document: {
          id: doc.id,
          filename: doc.title,
          file_type: doc.file_type,
          file_size: doc.file_size,
          content_hash: '',
          upload_time: doc.upload_time,
          last_modified: doc.upload_time,
          metadata: {
            title: doc.title,
            author: doc.metadata.author,
            description: doc.content,
            keywords: doc.metadata.keywords || [],
            publish_date: doc.metadata.publish_date,
            source: doc.metadata.source,
            language: 'zh',
            category: doc.metadata.category,
            tags: doc.metadata.tags || [],
            custom_fields: doc.metadata.custom_fields || {}
          },
          spatial_metadata: doc.spatial_info ? {
            geometry: doc.spatial_info.geometry,
            bounding_box: doc.spatial_info.bounding_box,
            address: doc.spatial_info.address,
            city: doc.spatial_info.city,
            province: doc.spatial_info.province,
            country: doc.spatial_info.country,
            coordinate_system: 'EPSG:4326'
          } : undefined,
          vector_embedding: undefined,
          is_indexed: true,
          indexing_status: 'completed',
          storage_path: '',
          access_url: doc.source_url,
          download_available: doc.download_available,
          download_url: doc.download_url,
          version: 1
        },
        highlights: {},
        explanation: `相似度: ${(doc.similarity * 100).toFixed(1)}%`,
        vector_distance: 1 - doc.similarity
      }));

      setSearchResults(results);

      // 更新聊天消息显示搜索结果
      const newMessage: ChatMessageType = {
        id: `search-${Date.now()}`,
        role: 'assistant',
        content: `已找到 ${results.length} 个相关文档。`,
        timestamp: new Date().toISOString(),
        metadata: {
          document_ids: results.map(r => r.document.id),
          citations: results.map(r => ({
            document_id: r.document.id,
            title: r.document.metadata.title,
            excerpt: r.document.metadata.description || '',
            confidence: r.score
          })),
          search_query: query
        }
      };

      setMessages(prev => [...prev, newMessage]);
    } catch (error) {
      console.error('搜索失败:', error);
      const errorMessage: ChatMessageType = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: '搜索过程中出现错误，请稍后重试。',
        timestamp: new Date().toISOString(),
        metadata: {}
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsSearching(false);
    }
  };

  // 停止生成函数
  const handleStopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsChatLoading(false);

      const stopMessage: ChatMessageType = {
        id: `stop-${Date.now()}`,
        role: 'assistant',
        content: '生成已停止。',
        timestamp: new Date().toISOString(),
        metadata: {}
      };
      setMessages(prev => [...prev, stopMessage]);
    }
  };

  /**
   * 从大模型回复中提取行政区划代码（ADCODE）并净化消息
   * @param content 原始消息内容
   * @returns 包含净化后内容和adcode的对象
   */
  const extractAdcodeAndPurify = (content: string): { purifiedContent: string; adcode?: string; name?: string } => {
    // 正则表达式匹配Markdown JSON代码块，增强容错性
    const regex = /```json\s*([\s\S]*?)\s*```/;
    const match = content.match(regex);

    if (!match) {
      return { purifiedContent: content.trim() };
    }

    try {
      const jsonStr = match[1];
      const parsed = JSON.parse(jsonStr);
      const adcode = parsed.adcode || parsed.ADCODE;
      // 兼容多种可能的名称键名
      const name = parsed.name || parsed.NAME || parsed.province || parsed.city || parsed.region_name;

      if (adcode && /^\d{6}$/.test(String(adcode))) {
        // 移除JSON代码块，净化内容
        const purifiedContent = content.replace(regex, '').trim();
        return { purifiedContent, adcode: String(adcode), name: name ? String(name) : undefined };
      }
    } catch (error) {
      console.warn('解析ADCODE JSON失败:', error);
    }

    // 如果解析失败，只移除代码块
    const purifiedContent = content.replace(regex, '').trim();
    return { purifiedContent };
  };

  // 聊天函数（集成AbortController）
  const handleChatSubmit = async (content: string) => {
    if (!content.trim()) return;

    const regionFromQuery = extractRegionFromQuery(content);
    const regionContext = regionFromQuery ?? activeRegion;
    const followUpContext = resolveFollowUpContext(content, messages, selectedDocument);
    if (regionFromQuery) {
      setActiveRegion(regionFromQuery);
    }

    // 构建历史记录：将当前消息列表转换为API格式
    const history = messages.map(msg => ({
      role: msg.role,
      content: msg.content
    }));

    // 添加用户消息
    const userMessage: ChatMessageType = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: content,
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, userMessage]);

    if (isCurrentRegionQuestion(content)) {
      const assistantMessage: ChatMessageType = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: regionContext
          ? `当前地图选中的区域是${regionContext.name}（ADCODE：${regionContext.adcode}）。`
          : '当前地图还没有选中具体区域。请先在地图上点击一个省级区域，或直接在问题中说明区域名称。',
        timestamp: new Date().toISOString(),
        metadata: {
          search_query: content,
          selected_region: regionContext ?? undefined
        }
      };
      setMessages(prev => [...prev, assistantMessage]);
      return;
    }

    // 创建新的AbortController
    abortControllerRef.current?.abort(); // 中止之前的请求
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    setIsChatLoading(true);

    try {
      // 发送到聊天API，传递signal
      const queryForBackend = buildRegionAwareQuery(content, regionContext);
      const contextualHistory = regionContext
        ? [
            {
              role: 'system',
              content: `当前地图选中区域：${regionContext.name}，ADCODE：${regionContext.adcode}。当用户提到“该地区”“当前区域”“这里”“当地”等指代时，均指这个区域。`
            },
            ...history
          ]
        : history;
      const response = await chatService.sendMessage(
        queryForBackend,
        undefined,
        contextualHistory,
        abortController.signal,
        followUpContext
      );
      if (response.quota) {
        updateQuota(response.quota);
      }

      // 检查是否被中止
      if (abortController.signal.aborted) {
        return;
      }

      // 转换references为citations
      const citations = (response.references || []).map(ref => ({
        document_id: ref.id,
        title: ref.title,
        excerpt: ref.content,
        confidence: ref.similarity
      }));

      // 转换references为文档
      const documents = (response.references || []).map(ref => ({
        id: ref.id,
        filename: ref.title,
        file_type: ref.file_type,
        file_size: ref.file_size,
        content_hash: '',
        upload_time: ref.upload_time,
        last_modified: ref.upload_time,
        metadata: {
          title: ref.title,
          author: ref.metadata?.author,
          description: ref.content,
          keywords: ref.metadata?.keywords || [],
          publish_date: ref.metadata?.publish_date,
          source: ref.metadata?.source,
          language: 'zh',
          category: ref.metadata?.category,
          tags: ref.metadata?.tags || [],
          custom_fields: ref.metadata?.custom_fields || {}
        },
        spatial_metadata: ref.spatial_info ? {
          geometry: ref.spatial_info.geometry,
          bounding_box: ref.spatial_info.bounding_box,
          address: ref.spatial_info.address,
          city: ref.spatial_info.city,
          province: ref.spatial_info.province,
          country: ref.spatial_info.country,
          coordinate_system: 'EPSG:4326'
        } : undefined,
        vector_embedding: undefined,
        is_indexed: true,
        indexing_status: 'completed',
        storage_path: '',
        access_url: ref.source_url,
        download_available: ref.download_available,
        download_url: ref.download_url,
        version: 1
      }));

      // 提取ADCODE并净化消息内容
      const { purifiedContent, adcode, name } = extractAdcodeAndPurify(response.message);

      // 如果提取到有效的ADCODE，写入全局 Store（双引擎自动响应）
      if (adcode) {
        // 如果没有提取到名称，或者名称本身看起来像个代码，则尝试进行简单的本地映射补全（仅省份级）
        let finalName = name;
        if (!finalName || /^\d+$/.test(String(finalName))) {
          const provinceMap: Record<string, string> = {
            '110000': '北京市', '120000': '天津市', '130000': '河北省', '140000': '山西省', '150000': '内蒙古自治区',
            '210000': '辽宁省', '220000': '吉林省', '230000': '黑龙江省', '310000': '上海市', '320000': '江苏省',
            '330000': '浙江省', '340000': '安徽省', '350000': '福建省', '360000': '江西省', '370000': '山东省',
            '410000': '河南省', '420000': '湖北省', '430000': '湖南省', '440000': '广东省', '450000': '广西壮族自治区',
            '460000': '海南省', '500000': '重庆市', '510000': '四川省', '520000': '贵州省', '530000': '云南省',
            '540000': '西藏自治区', '610000': '陕西省', '620000': '甘肃省', '630000': '青海省', '640000': '宁夏回族自治区',
            '650000': '新疆维吾尔自治区', '710000': '台湾省', '810000': '香港特别行政区', '820000': '澳门特别行政区'
          };
          finalName = PROVINCE_MAP[adcode] || adcode;
        }

        console.log(`提取到地理位置信息: ${finalName}(${adcode})，触发地图飞行`);
        setActiveRegion({ adcode, name: String(finalName) });
      }

      const assistantMessage: ChatMessageType = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: purifiedContent,
        timestamp: new Date().toISOString(),
        metadata: {
          document_ids: documents.map(d => d.id),
          citations: citations,
          search_query: queryForBackend,
          original_query: content,
          follow_up_context: followUpContext,
          selected_region: regionContext ?? undefined
        }
      };

      setMessages(prev => [...prev, assistantMessage]);

      // 如果有相关文档，更新搜索结果
      if (documents.length > 0) {
        // 将文档转换为SearchResult格式
        const newSearchResults: SearchResult[] = documents.map(doc => ({
          id: doc.id,
          score: 0.8, // 默认分数
          document: { ...doc, indexing_status: doc.indexing_status as Document['indexing_status'] },
          highlights: {},
          explanation: '来自聊天上下文'
        }));
        setSearchResults(prev => [...prev, ...newSearchResults]);
      }
    } catch (error: any) {
      // 检查是否为中止错误
      if (error.name === 'AbortError') {
        console.log('请求被用户中止');
        return;
      }

      console.error('聊天失败:', error);
      const errorMessage: ChatMessageType = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: '聊天过程中出现错误，请稍后重试。',
        timestamp: new Date().toISOString(),
        metadata: {}
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      // 清除AbortController引用
      if (!abortController.signal.aborted) {
        abortControllerRef.current = null;
      }
      setIsChatLoading(false);
    }
  };

  // 获取文档详情
  const fetchDocumentDetails = async (documentId: string) => {
    if (!documentId) return null;

    setIsLoadingDocument(true);
    try {
      const documentDetail = await documentService.getDocumentById(documentId);
      if (!documentDetail) return null;

      // 将DocumentDetail转换为Document
      const document: Document = {
        id: documentDetail.id,
        filename: documentDetail.title,
        file_type: documentDetail.file_info.type,
        file_size: documentDetail.file_info.size,
        content_hash: '',
        upload_time: documentDetail.file_info.upload_time,
        last_modified: documentDetail.file_info.upload_time,
        metadata: {
          title: documentDetail.title,
          author: documentDetail.metadata.author,
          description: documentDetail.content,
          keywords: documentDetail.metadata.keywords || [],
          publish_date: documentDetail.metadata.publish_date,
          source: documentDetail.metadata.source,
          language: 'zh',
          category: documentDetail.metadata.category,
          tags: documentDetail.metadata.tags || [],
          custom_fields: documentDetail.metadata.custom_fields || {}
        },
        spatial_metadata: documentDetail.spatial_info ? {
          geometry: documentDetail.spatial_info.geometry,
          bounding_box: documentDetail.spatial_info.bounding_box,
          address: documentDetail.spatial_info.address,
          city: documentDetail.spatial_info.city,
          province: documentDetail.spatial_info.province,
          country: documentDetail.spatial_info.country,
          coordinate_system: 'EPSG:4326'
        } : undefined,
        vector_embedding: undefined,
        is_indexed: true,
        indexing_status: 'completed',
        storage_path: '',
        access_url: documentDetail.download_url,
        download_available: documentDetail.download_available,
        download_url: documentDetail.download_url,
        version: 1
      };

      return document;
    } catch (error) {
      console.error('获取文档详情失败:', error);
      return null;
    } finally {
      setIsLoadingDocument(false);
    }
  };

  // 处理引用点击
  const handleDocumentDownload = async () => {
    if (!selectedDocument?.id || !selectedDocument.download_available || isDownloadingDocument) {
      return;
    }

    setIsDownloadingDocument(true);
    try {
      const { blob, filename } = await documentService.downloadDocument(selectedDocument.id);
      const objectUrl = window.URL.createObjectURL(blob);
      const link = window.document.createElement('a');
      link.href = objectUrl;
      link.download =
        filename ||
        selectedDocument.filename ||
        `${selectedDocument.id}.${selectedDocument.file_type || 'pdf'}`;
      window.document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch (error) {
      console.error('鏂囨。涓嬭浇澶辫触:', error);
    } finally {
      setIsDownloadingDocument(false);
    }
  };

  const handleCitationClick = async (documentId: string) => {
    const doc = await fetchDocumentDetails(documentId);
    if (doc) {
      handleReferenceClick(doc);
    }
  };

  // 初始化加载数据
  useEffect(() => {
    // 可以在这里加载初始数据
    const loadInitialData = async () => {
      // 示例：加载一些初始搜索
      // await handleSearch('国土空间规划');
    };
    loadInitialData();
  }, []);

  // 组件卸载时中止所有请求
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

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

  return (
    <div className="relative w-full h-screen text-on-background font-sans overflow-hidden" style={{background:'var(--color-background)'}}>
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
          visible={viewMode === '3D'}
          layers={layers}
          onReady={handleMapReady3D}
        />
        <OpenLayersMap
          theme={theme}
          visible={viewMode === '2D'}
          layers={layers}
          onReady={handleMapReady2D}
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
        style={{...glassStyle,border:'0.5px solid var(--color-outline)',boxShadow:'0 8px 32px rgba(0,0,0,0.1)'}}
      >
        <div className="flex items-center gap-6">
          {/* Logo */}
          <div className="flex items-center gap-2.5 font-headline">
            <div className="relative w-5 h-5">
              <div className="absolute inset-0 rotate-45 rounded-[3px]" style={{background:'#f07040',boxShadow:'0 0 10px rgba(240,112,64,0.7)'}} />
              <div className="absolute inset-[3px] rotate-45 rounded-[1px]" style={{background:'var(--color-background)'}} />
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
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full" style={{background:'rgba(16,185,129,0.08)',border:'0.5px solid rgba(16,185,129,0.2)'}}>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-soft" style={{boxShadow:'0 0 6px rgba(16,185,129,0.7)'}}></span>
            <span className="text-[12.5px] font-medium" style={{color:'rgba(16,185,129,0.8)'}}>已连接</span>
          </div>
          <div className="flex gap-1.5 items-center mr-2">
            {/* Theme Segmented Control */}
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

      {/* Side Nav - Removed as requested */}


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
          <div className="glass-light p-4 rounded-xl flex flex-col gap-3.5" style={{...glassLightStyle,minWidth:'168px',border:'0.5px solid var(--color-outline)',boxShadow:'0 8px 32px rgba(0,0,0,0.1)'}}>
            <div className="flex items-center gap-1.5 mb-0.5">
              <Layers className="w-3 h-3" style={{color:'rgba(240,112,64,0.7)'}} />
              <span className="text-[11.5px] font-semibold uppercase tracking-[0.15em]" style={{color:'rgba(240,112,64,0.65)'}}>图层控制</span>
            </div>
            {[
              { id: 'admin', label: '行政区划' },
              { id: 'wms', label: '卫星底图' }
            ].map(layer => {
              const isOn = layers[layer.id as keyof typeof layers];
              return (
                <div key={layer.id} className="flex items-center justify-between gap-4">
                  <span className={cn("text-[13.5px] font-medium transition-colors", isOn ? "text-on-background/80" : "text-on-background/35")}>{layer.label}</span>
                  <div className={`toggle-track ${isOn ? 'on' : 'off'}`} onClick={() => toggleLayer(layer.id as keyof typeof layers)}>
                    <motion.div
                      className={`toggle-thumb ${isOn ? 'on' : 'off'}`}
                      animate={{ x: isOn ? 17 : 3 }}
                      transition={{ type:'spring', stiffness:500, damping:30 }}
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
              key={activeRegion?.adcode ?? 'overview'}
              initial={{ opacity: 0, x: -6, scale: 0.97 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 6, scale: 0.97 }}
              transition={{ duration: 0.2 }}
              className="glass-light flex flex-col items-start px-4 py-3 rounded-xl"
              style={{...glassLightStyle,border:'0.5px solid var(--color-outline-glow)',boxShadow:'0 0 24px rgba(0,0,0,0.1)'}}
            >
              {activeRegion ? (
                <>
                  <span className="font-headline font-bold text-xl tracking-tight text-glow" style={{color:'var(--color-primary)'}}>{activeRegion.name}</span>
                  <span className="font-mono text-[11.5px] tracking-[0.18em] mt-0.5" style={{color:'var(--color-primary-container)', opacity: 0.6}}>ADCODE · {activeRegion.adcode}</span>
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
          <div className="glass p-[3px] rounded-full flex shadow-xl" style={{...glassStyle,border:'0.5px solid var(--color-outline)',boxShadow:'0 8px 32px rgba(0,0,0,0.1)'}}>
            {(['3D 地球','2D 地图'] as const).map((label,i) => {
              const mode = i===0 ? '3D' : '2D';
              const active = viewMode === mode;
              return (
                <button
                  key={mode}
                  onClick={() => handleViewModeSwitch(mode)}
                  className={cn("px-5 py-1.5 rounded-full text-xs font-semibold transition-all", !active && "text-on-background/35 hover:text-on-background/60")}
                  style={active ? {background:'var(--color-primary-container)',color:'var(--color-on-primary-fixed)',boxShadow:'0 0 12px var(--color-primary-glow)'} : {}}
                >{label}</button>
              );
            })}
          </div>
        </motion.div>

        {/* AI Chat Panel - Floating Right */}
        <motion.div
          className={cn(
            "absolute top-[80px] bottom-6 right-6 w-[420px] z-20",
            uiInteractive ? 'pointer-events-auto' : 'pointer-events-none'
          )}
          initial={false}
          animate={{
            opacity: uiVisible ? 1 : 0,
            x: uiVisible ? 0 : reduceMotion ? 10 : 42,
            y: uiVisible ? 0 : reduceMotion ? 6 : 18,
            scale: uiVisible ? 1 : reduceMotion ? 0.995 : 0.975,
          }}
          transition={getLayerTransition(reduceMotion ? 0.08 : 0.66)}
        >
          <div className="h-full rounded-2xl overflow-hidden glass border border-outline shadow-xl" style={glassStyle}>
            <Chat
              messages={messages}
              onSendMessage={handleChatSubmit}
              isLoading={isChatLoading}
              onStopGeneration={handleStopGeneration}
              inputValue={chatInput}
              onInputChange={setChatInput}
              onCitationClick={handleCitationClick}
              disabled={isSearching}
              title="Sentinel GeoAI"
              status={
                user?.role === 'visitor'
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

        {/* Reset View - Optimized Position to Bottom-Left Cluster */}
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
            onClick={resetView}
            className="glass-light flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium transition-all cursor-pointer"
            style={{...glassLightStyle,border:'0.5px solid var(--color-outline-glow)', color:'var(--color-primary-container)', boxShadow:'0 8px 32px rgba(0,0,0,0.1)'}}
            onMouseEnter={e=>{(e.currentTarget as HTMLElement).style.background='rgba(240,112,64,0.12)'}}
            onMouseLeave={e=>{(e.currentTarget as HTMLElement).style.background=''}}
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
            
            {/* Skip middle part for this specific edit to avoid too much text if needed, but here I should include enough to match */}
            <div className="flex-1 overflow-y-auto p-8 space-y-10 no-scrollbar">
              <div className="space-y-4">
                <div className="flex items-center gap-4">
                  <div className="w-16 h-16 bg-primary-container/10 flex items-center justify-center rounded-2xl">
                    <FileText className="w-10 h-10 text-primary-container" />
                  </div>
                  <div>
                    <h2 className="text-xl font-extrabold text-[#f0f0f0] leading-tight font-headline">{selectedDocument.metadata.title}</h2>
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
                      selectedDocument.indexing_status === 'completed'
                        ? 'bg-emerald-500/15 text-emerald-500'
                        : 'bg-yellow-500/15 text-yellow-500'
                    }`}>
                      {selectedDocument.indexing_status === 'completed' ? '已完成' : '待处理'}
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
