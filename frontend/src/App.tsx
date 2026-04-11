import React, { useState, useEffect, useRef, useCallback } from 'react';
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
  Radio
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import CesiumGlobe from './components/CesiumGlobe';
import OpenLayersMap from './components/OpenLayersMap';
import Chat from './components/Chat';
import { cn } from './lib/utils';
import { searchService } from './services/searchService';
import { chatService } from './services/chatService';
import { documentService } from './services/documentService';
import type { SearchResult, Document, ChatMessage as ChatMessageType, DocumentPreview } from './types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useMapStore, zoomToHeight, heightToZoom } from './store/useMapStore';

export default function App() {
  // ==================== 全局空间状态 ====================
  const viewMode = useMapStore((s) => s.viewMode);
  const setViewMode = useMapStore((s) => s.setViewMode);
  const activeRegion = useMapStore((s) => s.activeRegion);
  const setActiveRegion = useMapStore((s) => s.setActiveRegion);
  const setViewState = useMapStore((s) => s.setViewState);
  const resetView = useMapStore((s) => s.resetView);

  // 2D/3D 地图容器 ref，用于视角交接
  const olContainerRef = useRef<HTMLDivElement>(null);
  const cesiumContainerRef = useRef<HTMLDivElement>(null);

  // ==================== "视角交接仪式" ====================
  // 切换引擎前：从当前引擎快照视角 → 写入 Store → 新引擎读取 Store 恢复
  const handleViewModeSwitch = useCallback((targetMode: '2D' | '3D') => {
    if (targetMode === viewMode) return;

    if (viewMode === '3D' && targetMode === '2D') {
      // 3D → 2D：如果是自由视角（无选中省份），读取 Cesium 相机参数换算 zoom 写入 Store
      const { activeRegion } = useMapStore.getState();
      if (!activeRegion) {
        const cesiumEl = document.getElementById('cesiumContainer');
        if (cesiumEl && (cesiumEl as any).__snapshotView) {
          (cesiumEl as any).__snapshotView();
        }
        // 此时 store.viewState.height 已更新，补算 zoom
        const { height, center } = useMapStore.getState().viewState;
        const zoom = heightToZoom(height);
        setViewState({ zoom, center });
      }
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
      const height = zoomToHeight(zoom);
      setViewState({ height, center });
    }

    setViewMode(targetMode);
  }, [viewMode, setViewMode, setViewState]);
  const [layers, setLayers] = useState({
    admin: true,
    wms: true
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
    // 正则表达式匹配Markdown JSON代码块
    const regex = /```json\n([\s\S]*?)\n```/;
    const match = content.match(regex);

    if (!match) {
      return { purifiedContent: content.trim() };
    }

    try {
      const jsonStr = match[1];
      const parsed = JSON.parse(jsonStr);
      const adcode = parsed.adcode;
      const name = parsed.name;

      if (typeof adcode === 'string' && /^\d{6}$/.test(adcode)) {
        // 移除JSON代码块，净化内容
        const purifiedContent = content.replace(regex, '').trim();
        return { purifiedContent, adcode, name };
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

    // 创建新的AbortController
    abortControllerRef.current?.abort(); // 中止之前的请求
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    setIsChatLoading(true);

    try {
      // 发送到聊天API，传递signal
      const response = await chatService.sendMessage(content, undefined, history, abortController.signal);

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
        version: 1
      }));

      // 提取ADCODE并净化消息内容
      const { purifiedContent, adcode, name } = extractAdcodeAndPurify(response.message);

      // 如果提取到有效的ADCODE，写入全局 Store（双引擎自动响应）
      if (adcode) {
        console.log(`提取到地理位置信息: ${name || adcode}(${adcode})，触发地图飞行`);
        setActiveRegion({ adcode, name: name || adcode });
      }

      const assistantMessage: ChatMessageType = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: purifiedContent,
        timestamp: new Date().toISOString(),
        metadata: {
          document_ids: documents.map(d => d.id),
          citations: citations,
          search_query: content
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
        access_url: documentDetail.metadata.source_url,
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

  return (
    <div className="flex flex-col h-screen bg-surface-container-lowest text-on-background font-sans overflow-hidden">
      {/* Header */}
      <header className="h-[46px] w-full fixed top-0 left-0 z-50 glass flex items-center justify-between px-6 shadow-2xl border-b border-outline-variant/10">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 text-lg font-bold text-[#f0f0f0] font-headline">
            <div className="w-5 h-5 bg-primary-container rotate-45 flex items-center justify-center overflow-hidden">
              <div className="w-full h-full bg-surface-container-lowest scale-75 rotate-[-45deg]"></div>
            </div>
            <span>标准规范-智能空间查询系统</span>
          </div>
          <nav className="flex items-center h-[46px] ml-4">
            <a className="text-primary-container font-bold border-b-2 border-primary-container h-full flex items-center px-4 transition-all" href="#">检索</a>
            <a className="text-[#90909a] hover:text-[#f0f0f0] h-full flex items-center px-4 transition-colors" href="#">知识库</a>
            <a className="text-[#90909a] hover:text-[#f0f0f0] h-full flex items-center px-4 transition-colors" href="#">系统管理</a>
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 bg-surface-container px-3 py-1 rounded-full text-xs font-medium">
            <span className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]"></span>
            <span className="text-[#90909a]">已连接</span>
          </div>
          <div className="flex gap-2 items-center">
            <Radio className="w-5 h-5 text-[#90909a] hover:text-[#f0f0f0] cursor-pointer" />
            <Bell className="w-5 h-5 text-[#90909a] hover:text-[#f0f0f0] cursor-pointer" />
            <div className="w-7 h-7 rounded-full bg-surface-container-highest border border-outline-variant/20 overflow-hidden ml-2">
              <img
                className="w-full h-full object-cover"
                src="https://picsum.photos/seed/user/100/100"
                alt="Avatar"
                referrerPolicy="no-referrer"
              />
            </div>
          </div>
        </div>
      </header>

      {/* Side Nav */}
      <aside className="w-[64px] h-screen fixed left-0 top-[46px] z-40 bg-surface flex flex-col items-center py-6 gap-8 shadow-[4px_0_24px_rgba(0,0,0,0.5)] border-r border-outline-variant/10">
        <div className="group cursor-pointer">
          <MapIcon className="w-6 h-6 text-primary-container bg-primary-container/10 p-1 rounded-lg group-hover:scale-110 transition-transform" />
        </div>
        <div className="group cursor-pointer">
          <Microscope className="w-6 h-6 text-[#50505a] hover:text-[#90909a] group-hover:scale-110 transition-transform" />
        </div>
        <div className="group cursor-pointer">
          <BarChart3 className="w-6 h-6 text-[#50505a] hover:text-[#90909a] group-hover:scale-110 transition-transform" />
        </div>
        <div className="mt-auto group cursor-pointer">
          <Settings className="w-6 h-6 text-[#50505a] hover:text-[#90909a] group-hover:scale-110 transition-transform" />
        </div>
      </aside>

      {/* Main Content */}
      <main className="ml-[64px] pt-[46px] flex h-screen overflow-hidden">
        {/* Map Section */}
        <section className="w-[65%] h-full relative overflow-hidden bg-surface-container-lowest">
          <div className="absolute inset-0 z-0 bg-black">
            <CesiumGlobe visible={viewMode === '3D'} layers={layers} />
            <OpenLayersMap visible={viewMode === '2D'} layers={layers} />
          </div>

          {/* Layer Controls */}
          <div className="absolute top-6 left-6 z-10 flex flex-col gap-2">
            <div className="bg-surface-dim/80 glass p-4 rounded-xl shadow-2xl space-y-4 min-w-[180px] border border-outline-variant/10">
              <h3 className="text-xs font-bold text-primary-container uppercase tracking-widest flex items-center gap-2">
                <Layers className="w-4 h-4" /> 图层控制
              </h3>
              <div className="space-y-3">
                {[
                  { id: 'admin', label: '行政区划' },
                  { id: 'wms', label: 'WMS 底图' }
                ].map(layer => (
                  <div key={layer.id} className="flex items-center justify-between group">
                    <span className="text-sm text-[#90909a] group-hover:text-on-background transition-colors">{layer.label}</span>
                    <div
                      onClick={() => toggleLayer(layer.id as keyof typeof layers)}
                      className={cn(
                        "w-8 h-4 rounded-full relative cursor-pointer flex items-center px-0.5 transition-colors",
                        layers[layer.id as keyof typeof layers] ? "bg-primary-container/20" : "bg-surface-container-highest"
                      )}
                    >
                      <motion.div
                        animate={{ x: layers[layer.id as keyof typeof layers] ? 16 : 0 }}
                        className={cn(
                          "w-3 h-3 rounded-full shadow-lg transition-colors",
                          layers[layer.id as keyof typeof layers] ? "bg-primary-container" : "bg-[#50505a]"
                        )}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Info Badge — 订阅 activeRegion，动态渲染 */}
          <div className="absolute top-6 right-6 z-10">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeRegion?.adcode ?? 'overview'}
                initial={{ opacity: 0, y: -8, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, scale: 0.96 }}
                transition={{ duration: 0.25 }}
                className="bg-primary-container/10 border border-primary-container/20 glass px-6 py-3 rounded-xl flex flex-col items-end shadow-xl"
              >
                {activeRegion ? (
                  <>
                    <span className="text-primary-container font-bold text-2xl tracking-tight font-headline">
                      {activeRegion.name}
                    </span>
                    <span className="text-primary text-[10px] font-mono tracking-widest">
                      ADCODE: {activeRegion.adcode}
                    </span>
                  </>
                ) : (
                  <>
                    <span className="text-primary-container font-bold text-2xl tracking-tight font-headline">
                      中国全貌
                    </span>
                    <span className="text-primary text-[10px] font-mono tracking-widest">
                      OVERVIEW
                    </span>
                  </>
                )}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Mode Switcher — 带"视角交接仪式" */}
          <div className="absolute bottom-10 left-1/2 -translate-x-1/2 z-10">
            <div className="bg-surface-container-high/60 glass p-1 rounded-full flex gap-1 shadow-2xl border border-outline-variant/10">
              <button
                onClick={() => handleViewModeSwitch('3D')}
                className={cn(
                  "px-6 py-1.5 rounded-full text-sm font-bold transition-all",
                  viewMode === '3D' ? "bg-primary-container text-on-primary-fixed shadow-lg" : "text-[#90909a] hover:text-[#f0f0f0]"
                )}
              >
                3D 地球
              </button>
              <button
                onClick={() => handleViewModeSwitch('2D')}
                className={cn(
                  "px-6 py-1.5 rounded-full text-sm font-bold transition-all",
                  viewMode === '2D' ? "bg-primary-container text-on-primary-fixed shadow-lg" : "text-[#90909a] hover:text-[#f0f0f0]"
                )}
              >
                2D 地图
              </button>
            </div>
          </div>

          {/* Lat-Long Display */}
          <div className="absolute bottom-6 left-6 z-10 font-mono text-[10px] text-[#50505a] flex gap-4 bg-surface-container-lowest/50 glass px-3 py-1 rounded-md">
            <span>LNG: 104.0665</span>
            <span>LAT: 30.5723</span>
            <span>ELE: 500M</span>
            <span className="text-primary-container/50">WGS84</span>
          </div>

          {/* Reset View 按钮 — 清空选中 + 双引擎飞回初始视角 */}
          <div className="absolute bottom-6 right-6 z-10">
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={resetView}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl
                         bg-primary-container/10 glass border border-primary-container/20
                         text-primary-container text-sm font-bold
                         hover:bg-primary-container hover:text-on-primary-fixed
                         shadow-xl transition-colors cursor-pointer"
            >
              <RotateCcw className="w-4 h-4" />
              复位视角
            </motion.button>
          </div>
        </section>

        {/* AI Chat Section */}
        <section className="w-[35%] h-full">
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
            status="模型就绪 · RAG 已同步"
            quickTags={['# 城镇开发边界', '# 永久基本农田', '# 生态保护红线', '# 四川技术规范']}
          />
        </section>

        {/* Details Drawer */}
        <AnimatePresence>
          {isDrawerOpen && selectedDocument && (
            <motion.section
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className="fixed right-0 top-[46px] w-[35%] h-[calc(100vh-46px)] bg-surface-dim z-50 border-l border-outline-variant/20 shadow-[-10px_0_40px_rgba(0,0,0,0.5)] flex flex-col"
            >
              <div className="p-6 border-b border-outline-variant/10 flex items-center justify-between">
                <h3 className="text-lg font-bold text-on-background flex items-center gap-3 font-headline">
                  <ArrowLeft
                    className="w-5 h-5 text-[#90909a] hover:text-[#f0f0f0] cursor-pointer"
                    onClick={() => setIsDrawerOpen(false)}
                  />
                  标准详情
                </h3>
                <X
                  className="w-5 h-5 text-[#50505a] hover:text-red-500 cursor-pointer transition-colors"
                  onClick={() => setIsDrawerOpen(false)}
                />
              </div>

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
                      <p className="text-[10px] text-[#50505a] uppercase font-bold tracking-widest mb-1">文件类型</p>
                      <p className="text-sm text-on-background">{selectedDocument.file_type}</p>
                    </div>
                    <div>
                      <p className="text-[10px] text-[#50505a] uppercase font-bold tracking-widest mb-1">文件大小</p>
                      <p className="text-sm text-on-background">
                        {selectedDocument.file_size > 1024 * 1024
                          ? `${(selectedDocument.file_size / (1024 * 1024)).toFixed(2)} MB`
                          : `${(selectedDocument.file_size / 1024).toFixed(2)} KB`}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] text-[#50505a] uppercase font-bold tracking-widest mb-1">上传时间</p>
                      <p className="text-sm text-on-background">
                        {new Date(selectedDocument.upload_time).toLocaleDateString('zh-CN')}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] text-[#50505a] uppercase font-bold tracking-widest mb-1">索引状态</p>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        selectedDocument.indexing_status === 'completed'
                          ? 'bg-emerald-500/10 text-emerald-500'
                          : selectedDocument.indexing_status === 'processing'
                          ? 'bg-blue-500/10 text-blue-500'
                          : selectedDocument.indexing_status === 'failed'
                          ? 'bg-red-500/10 text-red-500'
                          : 'bg-yellow-500/10 text-yellow-500'
                      }`}>
                        {selectedDocument.indexing_status === 'completed' ? '已完成' :
                         selectedDocument.indexing_status === 'processing' ? '处理中' :
                         selectedDocument.indexing_status === 'failed' ? '失败' : '待处理'}
                      </span>
                    </div>
                  </div>
                </div>

                {selectedDocument.metadata.description && (
                  <div className="space-y-3">
                    <h4 className="text-xs font-bold text-[#90909a] uppercase tracking-widest">描述</h4>
                    <p className="text-sm text-[#90909a] leading-relaxed">
                      {selectedDocument.metadata.description}
                    </p>
                  </div>
                )}

                {selectedDocument.metadata.keywords && selectedDocument.metadata.keywords.length > 0 && (
                  <div className="space-y-3">
                    <h4 className="text-xs font-bold text-[#90909a] uppercase tracking-widest">关键词</h4>
                    <div className="flex flex-wrap gap-2">
                      {selectedDocument.metadata.keywords.map((keyword, idx) => (
                        <span key={idx} className="bg-surface-container px-2 py-1 rounded text-xs text-on-background">
                          {keyword}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {selectedDocument.spatial_metadata && (
                  <div className="space-y-3">
                    <h4 className="text-xs font-bold text-[#90909a] uppercase tracking-widest">空间信息</h4>
                    <div className="grid grid-cols-2 gap-4">
                      {selectedDocument.spatial_metadata.address && (
                        <div>
                          <p className="text-[10px] text-[#50505a] uppercase font-bold tracking-widest mb-1">地址</p>
                          <p className="text-sm text-on-background">{selectedDocument.spatial_metadata.address}</p>
                        </div>
                      )}
                      {selectedDocument.spatial_metadata.city && (
                        <div>
                          <p className="text-[10px] text-[#50505a] uppercase font-bold tracking-widest mb-1">城市</p>
                          <p className="text-sm text-on-background">{selectedDocument.spatial_metadata.city}</p>
                        </div>
                      )}
                      {selectedDocument.spatial_metadata.province && (
                        <div>
                          <p className="text-[10px] text-[#50505a] uppercase font-bold tracking-widest mb-1">省份</p>
                          <p className="text-sm text-on-background">{selectedDocument.spatial_metadata.province}</p>
                        </div>
                      )}
                      {selectedDocument.spatial_metadata.country && (
                        <div>
                          <p className="text-[10px] text-[#50505a] uppercase font-bold tracking-widest mb-1">国家</p>
                          <p className="text-sm text-on-background">{selectedDocument.spatial_metadata.country}</p>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                <div className="pt-8">
                  {selectedDocument.access_url ? (
                    <a
                      href={selectedDocument.access_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="w-full bg-surface-container-highest border border-outline-variant/30 py-4 rounded-xl text-on-background text-sm font-bold hover:bg-surface-bright transition-colors flex items-center justify-center gap-3"
                    >
                      <Download className="w-5 h-5 text-primary-container" /> 下载文档
                    </a>
                  ) : (
                    <button
                      onClick={() => alert('文档暂不可下载')}
                      className="w-full bg-surface-container-highest border border-outline-variant/30 py-4 rounded-xl text-on-background text-sm font-bold hover:bg-surface-bright transition-colors flex items-center justify-center gap-3 opacity-50 cursor-not-allowed"
                    >
                      <Download className="w-5 h-5 text-primary-container" /> 文档暂不可下载
                    </button>
                  )}
                </div>
              </div>
            </motion.section>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}