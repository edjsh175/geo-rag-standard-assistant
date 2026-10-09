import { useState, useEffect, useRef, useCallback } from 'react';
import type { ChatMessage as ChatMessageType, Document, FollowUpContext } from '../types';
import { chatService } from '../services/chatService';
import { registerVectorDataset } from '../gis/fileReferenceStore';
import { AgentEventProjector } from '../components/agent/eventProjector';
import type { AgentTurnViewModel } from '../components/agent/types';
import {
  AgentSessionNotFoundError,
  clearAgentSessionId,
  createAgentSession,
  deleteAgentSession,
  listAgentSessions,
  readAgentSessionId,
  restoreAgentSession,
  saveAgentSessionId,
  type AgentSessionSummary,
} from '../services/agentHistory';
import { toFrontendDocumentFromResult } from './useDocumentManager';

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

export const createWelcomeMessage = (): ChatMessageType => ({
  id: 'init-1',
  role: 'assistant',
  content: `您好！我是 **GeoAI 空间规划智能体**。

已接入国土自然资源知识库与 WebGIS/PostGIS 空间底座，支持规划咨询与地图协同：

- 📚 **规范溯源**：规程标准权威问答与规划法规条款精准溯源
- 🗺️ **地图协同**：二三维联动漫游、图层显隐与样式定制（支持 📎 登记矢量数据）
- 📐 **空间分析**：PostGIS 拓扑相交、要素查验与几何计算

您可以直接提问规划业务（如 *“检索城镇开发边界划定标准”*），或发出地图操作指令（如 *“定位到成都市”*）。`,
  timestamp: new Date().toISOString(),
  metadata: { document_ids: [], citations: [] },
});

export const resolveFollowUpContext = (
  _content: string,
  _messages: ChatMessageType[],
  selectedDocument: Document | null
): FollowUpContext | undefined => {
  if (selectedDocument) {
    return {
      target_document_id: selectedDocument.id,
      candidate_documents: [
        {
          id: selectedDocument.id,
          title: selectedDocument.metadata.title,
          rank: 1,
        },
      ],
      resolution_source: 'selected_document',
    };
  }
  return undefined;
};

interface UseAgentSessionProps {
  user: any;
  updateQuota: (quota: any) => void;
  activeRegion: { adcode: string; name: string } | null;
  setActiveRegion: (region: { adcode: string; name: string } | null) => void;
  selectedDocument: Document | null;
  onDocumentsFound?: (docs: Document[]) => void;
}

export function useAgentSession({
  user,
  updateQuota,
  activeRegion,
  setActiveRegion,
  selectedDocument,
  onDocumentsFound,
}: UseAgentSessionProps) {
  const [chatInput, setChatInput] = useState('');
  const [messages, setMessages] = useState<ChatMessageType[]>([createWelcomeMessage()]);
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [reviewerEnabled, setReviewerEnabled] = useState(false);
  const [activeTurn, setActiveTurn] = useState<AgentTurnViewModel | null>(null);
  const conversationIdRef = useRef<string | undefined>(undefined);
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>(undefined);
  const [agentSessions, setAgentSessions] = useState<AgentSessionSummary[]>([]);
  const [isHistoryRestoring, setIsHistoryRestoring] = useState(false);
  const [historyRestoreError, setHistoryRestoreError] = useState(false);
  const [historyRetryKey, setHistoryRetryKey] = useState(0);
  const historyRestorePromiseRef = useRef<Promise<boolean> | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeProjectorRef = useRef<AgentEventProjector | null>(null);

  useEffect(() => {
    if (!user) return;
    let current = true;
    const controller = new AbortController();
    setHistoryRestoreError(false);
    setIsHistoryRestoring(true);
    const restoreTask = (async () => {
      try {
        const sessions = await listAgentSessions(controller.signal);
        if (!current) return false;
        setAgentSessions(sessions);
        const savedSessionId = readAgentSessionId(user);
        const sessionId = savedSessionId && sessions.some((item) => item.session_id === savedSessionId)
          ? savedSessionId
          : sessions[0]?.session_id;
        if (!sessionId) {
          conversationIdRef.current = undefined;
          setActiveSessionId(undefined);
          clearAgentSessionId(user);
          setMessages([createWelcomeMessage()]);
          return true;
        }

        conversationIdRef.current = sessionId;
        setActiveSessionId(sessionId);
        saveAgentSessionId(user, sessionId);
        const restored = await restoreAgentSession(sessionId, user, controller.signal);
        if (!current) return false;
        conversationIdRef.current = restored.sessionId || sessionId;
        setActiveSessionId(restored.sessionId || sessionId);
        setMessages(restored.messages.length ? restored.messages : [createWelcomeMessage()]);
        return true;
      } catch (error) {
        if (!current || controller.signal.aborted) return false;
        if (error instanceof AgentSessionNotFoundError) {
          conversationIdRef.current = undefined;
          setActiveSessionId(undefined);
          setMessages([createWelcomeMessage()]);
          return true;
        }
        console.warn('恢复聊天历史失败:', error);
        setHistoryRestoreError(true);
        return false;
      } finally {
        if (current) setIsHistoryRestoring(false);
      }
    })();
    historyRestorePromiseRef.current = restoreTask;

    return () => {
      current = false;
      controller.abort();
    };
  }, [user?.role, user?.username, user?.visitor_id, historyRetryKey]);

  const refreshAgentSessions = useCallback(async () => {
    const sessions = await listAgentSessions();
    setAgentSessions(sessions);
  }, []);

  const selectAgentSession = useCallback(async (sessionId: string) => {
    if (!user || sessionId === conversationIdRef.current) return;
    setHistoryRestoreError(false);
    setIsHistoryRestoring(true);
    const task = (async () => {
      try {
        const restored = await restoreAgentSession(sessionId, user);
        conversationIdRef.current = restored.sessionId || sessionId;
        setActiveSessionId(restored.sessionId || sessionId);
        saveAgentSessionId(user, restored.sessionId || sessionId);
        setMessages(restored.messages.length ? restored.messages : [createWelcomeMessage()]);
        return true;
      } catch (error) {
        if (error instanceof AgentSessionNotFoundError) {
          await refreshAgentSessions();
        }
        console.warn('切换会话失败:', error);
        setHistoryRestoreError(true);
        return false;
      } finally {
        setIsHistoryRestoring(false);
      }
    })();
    historyRestorePromiseRef.current = task;
    await task;
  }, [refreshAgentSessions, user]);

  const handleCreateAgentSession = useCallback(async () => {
    if (!user) return;
    const created = await createAgentSession();
    conversationIdRef.current = created.session_id;
    setActiveSessionId(created.session_id);
    saveAgentSessionId(user, created.session_id);
    setAgentSessions((current) => [created, ...current.filter((item) => item.session_id !== created.session_id)]);
    setMessages([createWelcomeMessage()]);
    setActiveTurn(null);
    setHistoryRestoreError(false);
  }, [user]);

  const handleDeleteAgentSession = useCallback(async (sessionId: string) => {
    if (!user) return;
    await deleteAgentSession(sessionId);
    const remaining = agentSessions.filter((item) => item.session_id !== sessionId);
    setAgentSessions(remaining);
    if (sessionId !== conversationIdRef.current) return;

    conversationIdRef.current = undefined;
    setActiveSessionId(undefined);
    clearAgentSessionId(user);
    if (remaining.length > 0) {
      await selectAgentSession(remaining[0].session_id);
    } else {
      setMessages([createWelcomeMessage()]);
      setHistoryRestoreError(false);
    }
  }, [agentSessions, selectAgentSession, user]);

  const retryHistoryRestore = useCallback(() => {
    setHistoryRetryKey((prev) => prev + 1);
  }, []);

  const handleStopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      if (activeTurn?.sessionId && activeTurn?.turnId) {
        void chatService.cancelTurn(activeTurn.sessionId, activeTurn.turnId, 'user_stop')
          .catch((error) => console.warn('服务端停止请求未确认:', error));
      }
      const observedTurn = activeProjectorRef.current?.snapshot();
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsChatLoading(false);
      setActiveTurn(null);
      activeProjectorRef.current = null;

      const stopMessage: ChatMessageType = {
        id: `stop-${Date.now()}`,
        role: 'assistant',
        content: '已请求停止生成。',
        timestamp: new Date().toISOString(),
        metadata: {
          agent_turn: observedTurn?.items.length ? {
            ...observedTurn,
            interruption: { kind: 'stopped', message: '已停止接收执行事件，服务端执行状态可刷新查看。' },
          } : undefined,
        }
      };
      setMessages(prev => [...prev, stopMessage]);
    }
  }, [activeTurn]);

  const handleChatSubmit = useCallback(async (content: string) => {
    if (!content.trim()) return;
    if (historyRestorePromiseRef.current && !(await historyRestorePromiseRef.current)) return;
    if (historyRestoreError) return;
    if (abortControllerRef.current && !abortControllerRef.current.signal.aborted) return;

    const regionContext = activeRegion;
    const followUpContext = resolveFollowUpContext(content, messages, selectedDocument);

    const history = messages
      .filter((msg): msg is ChatMessageType & { role: 'user' | 'assistant' } =>
        (msg.role === 'user' || msg.role === 'assistant') && msg.content.trim().length > 0
      )
      .map(msg => ({
        role: msg.role,
        content: msg.content.slice(0, 4000)
      }));

    const userMessage: ChatMessageType = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: content,
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, userMessage]);

    abortControllerRef.current?.abort();
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    setIsChatLoading(true);
    const projector = new AgentEventProjector();
    activeProjectorRef.current = projector;
    let boundTurnId: string | undefined;
    setActiveTurn(projector.snapshot());

    try {
      const response = await chatService.sendMessage(
        content,
        conversationIdRef.current,
        history,
        abortController.signal,
        followUpContext,
        (agentEvent) => {
          if (abortController.signal.aborted || abortControllerRef.current !== abortController) return;
          if (agentEvent.session_id) {
            conversationIdRef.current = agentEvent.session_id;
            setActiveSessionId(agentEvent.session_id);
            if (user) saveAgentSessionId(user, agentEvent.session_id);
          }
          if (agentEvent.event_type === 'session_started') return;
          if (!boundTurnId && (agentEvent.event_type === 'browser_tool_cancelled' || agentEvent.event_type === 'run_cancelled')) return;
          boundTurnId ||= agentEvent.turn_id || undefined;
          projector.applyEvent(agentEvent);
          setActiveTurn(projector.snapshot());
        },
        reviewerEnabled,
      );

      if (abortController.signal.aborted || abortControllerRef.current !== abortController) {
        return;
      }
      if (response.quota) updateQuota(response.quota);

      const citations = (response.references || []).map(ref => ({
        document_id: ref.id,
        title: ref.title,
        excerpt: ref.content,
        confidence: ref.similarity
      }));

      const documents = (response.references || []).map(toFrontendDocumentFromResult);

      const structuredMap = response.map_action;
      const purifiedContent = response.message.trim();
      const adcode = structuredMap?.adcode;
      const name = structuredMap?.name;

      if (adcode) {
        let finalName = name;
        if (!finalName || /^\d+$/.test(String(finalName))) {
          finalName = PROVINCE_MAP[String(adcode)] || String(adcode);
        }
        setActiveRegion({ adcode: String(adcode), name: String(finalName) });
      }

      const finalTurn = projector.snapshot();
      if (response.transport_error) {
        finalTurn.interruption = { kind: 'connection_error', message: response.transport_error };
      }
      const assistantMessage: ChatMessageType = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: purifiedContent,
        timestamp: new Date().toISOString(),
        metadata: {
          document_ids: documents.map(d => d.id),
          citations: citations,
          search_query: content,
          original_query: content,
          follow_up_context: followUpContext,
          selected_region: regionContext ?? undefined,
          agent_turn: finalTurn.items.length > 0 ? finalTurn : undefined
        }
      };

      setMessages(prev => [...prev, assistantMessage]);
      void refreshAgentSessions().catch((error) => console.warn('刷新会话列表失败:', error));

      if (documents.length > 0 && onDocumentsFound) {
        onDocumentsFound(documents);
      }
    } catch (error: any) {
      if (abortController.signal.aborted || abortControllerRef.current !== abortController || error.name === 'AbortError') {
        return;
      }
      console.error('聊天失败:', error);
      const errorMessage: ChatMessageType = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: '聊天过程中出现错误，请稍后重试。',
        timestamp: new Date().toISOString(),
        metadata: {
          agent_turn: projector.snapshot().items.length ? {
            ...projector.snapshot(),
            interruption: { kind: 'connection_error', message: '连接中断，已保留收到的执行过程。' },
          } : undefined,
        }
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
        activeProjectorRef.current = null;
        setIsChatLoading(false);
        setActiveTurn(null);
      }
    }
  }, [activeRegion, messages, onDocumentsFound, reviewerEnabled, selectedDocument, setActiveRegion, updateQuota, user, refreshAgentSessions]);

  const handleVectorFilesSelected = useCallback(async (files: File[]) => {
    const registered = await registerVectorDataset(files);
    return registered.name;
  }, []);

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  return {
    chatInput,
    setChatInput,
    messages,
    setMessages,
    isChatLoading,
    reviewerEnabled,
    setReviewerEnabled,
    activeTurn,
    activeSessionId,
    agentSessions,
    isHistoryRestoring,
    historyRestoreError,
    retryHistoryRestore,
    refreshAgentSessions,
    selectAgentSession,
    handleCreateAgentSession,
    handleDeleteAgentSession,
    handleChatSubmit,
    handleStopGeneration,
    handleVectorFilesSelected,
  };
}
