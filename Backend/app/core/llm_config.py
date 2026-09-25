"""
大语言模型配置管理器
支持 OpenAI、智谱AI、DeepSeek 等
"""

import logging
from typing import Optional, Dict, Any, AsyncGenerator
from enum import Enum
import asyncio

from openai import AsyncOpenAI
import httpx

from .config import settings

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """大模型提供商枚举"""
    OPENAI = "openai"
    ZHIPU = "zhipu"
    DEEPSEEK = "deepseek"


class EmbeddingProvider(str, Enum):
    """Embedding 模型提供商枚举"""
    OPENAI = "openai"
    ZHIPU = "zhipu"
    OLLAMA = "ollama"
    SENTENCE_TRANSFORMERS = "sentence_transformers"


class LLMConfig:
    """大语言模型配置管理器"""

    def __init__(self):
        self.openai_client: Optional[AsyncOpenAI] = None
        self.embedding_provider: EmbeddingProvider = EmbeddingProvider.OPENAI
        self._initialize()

    def _initialize(self):
        """初始化大模型客户端"""
        # 初始化 OpenAI 客户端
        if settings.OPENAI_API_KEY:
            proxy = (settings.OPENAI_PROXY or "").strip() or None
            self.openai_client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                http_client=httpx.AsyncClient(
                    timeout=60.0,
                    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                    proxies=proxy,
                    trust_env=False,
                )
            )
            logger.info("OpenAI 客户端初始化成功")
        else:
            logger.warning("OpenAI API Key 未配置，部分功能可能不可用")

        # 显式配置 Embedding 提供商时优先使用它，否则保持按 LLM_PROVIDER 推断的旧行为。
        configured_embedding_provider = (settings.EMBEDDING_PROVIDER or "").strip().lower()
        if configured_embedding_provider:
            try:
                self.embedding_provider = EmbeddingProvider(configured_embedding_provider)
            except ValueError as exc:
                supported = ", ".join(provider.value for provider in EmbeddingProvider)
                raise ValueError(
                    f"不支持的 Embedding 提供商: {settings.EMBEDDING_PROVIDER}，可选值: {supported}"
                ) from exc
        elif settings.LLM_PROVIDER == LLMProvider.ZHIPU:
            self.embedding_provider = EmbeddingProvider.ZHIPU
        elif settings.LLM_PROVIDER == LLMProvider.DEEPSEEK:
            self.embedding_provider = EmbeddingProvider.OPENAI  # DeepSeek 使用 OpenAI 兼容接口
        else:
            self.embedding_provider = EmbeddingProvider.OPENAI

        if (
            self.embedding_provider == EmbeddingProvider.OLLAMA
            and settings.OLLAMA_EMBEDDING_DIMENSIONS != settings.PG_VECTOR_DIMENSION
        ):
            raise ValueError(
                "OLLAMA_EMBEDDING_DIMENSIONS must match PG_VECTOR_DIMENSION "
                f"({settings.OLLAMA_EMBEDDING_DIMENSIONS} != {settings.PG_VECTOR_DIMENSION})"
            )
        if (
            self.embedding_provider == EmbeddingProvider.OLLAMA
            and settings.PG_VECTOR_DIMENSION != 2048
        ):
            raise ValueError(
                "The current policy_chunks and document_chunks schemas require 2048-dimensional embeddings"
            )

    def get_openai_client(self) -> AsyncOpenAI:
        """获取 OpenAI 客户端"""
        if not self.openai_client:
            raise RuntimeError("OpenAI 客户端未初始化")
        return self.openai_client

    @property
    def supports_reasoning(self) -> bool:
        """Whether a dedicated reasoning-capable model is explicitly configured."""
        return bool(settings.LLM_REASONING_MODEL)

    def resolve_main_model(self, *, thinking: bool) -> str:
        if thinking and settings.LLM_REASONING_MODEL:
            return settings.LLM_REASONING_MODEL
        provider = settings.LLM_PROVIDER
        if provider == LLMProvider.OPENAI:
            return settings.OPENAI_MODEL
        if provider == LLMProvider.ZHIPU:
            return settings.ZHIPU_MODEL
        if provider == LLMProvider.DEEPSEEK:
            return settings.DEEPSEEK_MODEL
        raise ValueError(f"不支持的 LLM 提供商: {provider}")

    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        获取文本的向量嵌入

        Args:
            texts: 文本列表

        Returns:
            向量嵌入列表
        """
        if self.embedding_provider == EmbeddingProvider.OPENAI:
            return await self._get_openai_embeddings(texts)
        elif self.embedding_provider == EmbeddingProvider.ZHIPU:
            return await self._get_zhipu_embeddings(texts)
        elif self.embedding_provider == EmbeddingProvider.OLLAMA:
            return await self._get_ollama_embeddings(texts)
        else:
            raise NotImplementedError(f"不支持的 Embedding 提供商: {self.embedding_provider}")

    async def _get_openai_embeddings(self, texts: list[str]) -> list[list[float]]:
        """使用 OpenAI 获取向量嵌入"""
        if not self.openai_client:
            raise RuntimeError("OpenAI 客户端未初始化")

        try:
            logger.debug(f"请求Embedding，模型: {settings.EMBEDDING_MODEL}, 文本数量: {len(texts)}, 第一段文本前100字符: {texts[0][:100]}...")
            response = await self.openai_client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=texts,
                encoding_format="float"
            )
            embeddings = [item.embedding for item in response.data]
            logger.debug(f"Embedding返回成功，数量: {len(embeddings)}, 维度: {len(embeddings[0]) if embeddings else 0}")
            return embeddings
        except Exception as e:
            logger.error(f"OpenAI Embedding 请求失败: {e}", exc_info=True)
            raise

    async def _get_zhipu_embeddings(self, texts: list[str]) -> list[list[float]]:
        """使用智谱AI获取向量嵌入"""
        if not settings.ZHIPU_API_KEY:
            raise RuntimeError("智谱AI API Key 未配置")

        # 智谱AI Embedding API 调用
        # 这里需要根据实际 API 实现
        raise NotImplementedError("智谱AI Embedding 功能待实现")

    async def _get_ollama_embeddings(self, texts: list[str]) -> list[list[float]]:
        """使用本地 Ollama 获取批量文本向量。"""
        if not texts:
            return []
        if settings.OLLAMA_EMBEDDING_DIMENSIONS <= 0:
            raise RuntimeError("OLLAMA_EMBEDDING_DIMENSIONS 必须为正整数")

        base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        payload = {
            "model": settings.OLLAMA_EMBEDDING_MODEL,
            "input": texts,
            "dimensions": settings.OLLAMA_EMBEDDING_DIMENSIONS,
        }
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=httpx.Timeout(60.0, connect=10.0),
                trust_env=False,
            ) as client:
                response = await client.post("/api/embed", json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            logger.error("Ollama Embedding 请求失败: %s", exc, exc_info=True)
            raise RuntimeError(
                f"Ollama Embedding 请求失败（{base_url}/api/embed，模型 {settings.OLLAMA_EMBEDDING_MODEL}）: {exc}"
            ) from exc
        except ValueError as exc:
            raise RuntimeError("Ollama Embedding 返回了无效 JSON") from exc

        embeddings = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(embeddings, list):
            raise RuntimeError("Ollama Embedding 响应缺少 embeddings 数组")
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Ollama Embedding 返回数量不匹配: 期望 {len(texts)}，实际 {len(embeddings)}"
            )

        expected_dimensions = settings.OLLAMA_EMBEDDING_DIMENSIONS
        for index, embedding in enumerate(embeddings):
            if not isinstance(embedding, list) or len(embedding) != expected_dimensions:
                actual_dimensions = len(embedding) if isinstance(embedding, list) else "非数组"
                raise RuntimeError(
                    f"Ollama Embedding 第 {index} 项维度不匹配: "
                    f"期望 {expected_dimensions}，实际 {actual_dimensions}"
                )
        return embeddings

    async def chat_completion(
        self,
        messages: list[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        request_reasoning: bool = False,
        timeout_seconds: Optional[float] = None,
        **kwargs
    ) -> str:
        """
        聊天补全接口

        Args:
            messages: 消息列表
            model: 模型名称，如果为 None 则使用配置的默认模型
            temperature: 温度参数
            **kwargs: 其他参数

        Returns:
            模型响应文本
        """
        provider = settings.LLM_PROVIDER
        selected_model = model
        if request_reasoning:
            if not self.supports_reasoning:
                raise RuntimeError("reasoning was requested but no reasoning model is configured")
        if selected_model is None:
            selected_model = self.resolve_main_model(thinking=request_reasoning)

        if provider == LLMProvider.OPENAI:
            return await self._openai_chat_completion(
                messages,
                selected_model,
                temperature,
                timeout_seconds=timeout_seconds,
                **kwargs,
            )
        elif provider == LLMProvider.ZHIPU:
            return await self._zhipu_chat_completion(messages, selected_model, temperature, **kwargs)
        elif provider == LLMProvider.DEEPSEEK:
            return await self._deepseek_chat_completion(
                messages,
                selected_model,
                temperature,
                timeout_seconds=timeout_seconds,
                **kwargs,
            )
        else:
            raise ValueError(f"不支持的 LLM 提供商: {provider}")

    async def _openai_chat_completion(
        self,
        messages: list[Dict[str, str]],
        model: Optional[str],
        temperature: float,
        timeout_seconds: Optional[float] = None,
        **kwargs
    ) -> str:
        """OpenAI 聊天补全"""
        if not self.openai_client:
            raise RuntimeError("OpenAI 客户端未初始化")

        try:
            coro = self.openai_client.chat.completions.create(
                model=model or settings.OPENAI_MODEL,
                messages=messages,
                temperature=temperature,
                **kwargs
            )
            response = await asyncio.wait_for(coro, timeout=timeout_seconds or 30.0)
            return response.choices[0].message.content
        except asyncio.TimeoutError:
            logger.error("OpenAI 聊天请求超时 (Circuit Breaker触发)")
            raise TimeoutError("大模型上游服务响应超时")
        except Exception as e:
            logger.error(f"OpenAI 聊天请求失败: {e}")
            raise

    async def _zhipu_chat_completion(
        self,
        messages: list[Dict[str, str]],
        model: Optional[str],
        temperature: float,
        **kwargs
    ) -> str:
        """智谱AI 聊天补全"""
        if not settings.ZHIPU_API_KEY:
            raise RuntimeError("智谱AI API Key 未配置")

        # 智谱AI API 调用
        # 这里需要根据实际 API 实现
        raise NotImplementedError("智谱AI 聊天功能待实现")

    async def _deepseek_chat_completion(
        self,
        messages: list[Dict[str, str]],
        model: Optional[str],
        temperature: float,
        timeout_seconds: Optional[float] = None,
        **kwargs
    ) -> str:
        """DeepSeek 聊天补全"""
        if not settings.DEEPSEEK_API_KEY:
            raise RuntimeError("DeepSeek API Key 未配置")

        # DeepSeek 使用 OpenAI 兼容接口
        client = self._create_deepseek_client()
        try:
            coro = client.chat.completions.create(
                model=model or settings.DEEPSEEK_MODEL,
                messages=messages,
                temperature=temperature,
                **kwargs
            )
            response = await asyncio.wait_for(coro, timeout=timeout_seconds or 30.0)
            return response.choices[0].message.content
        except asyncio.TimeoutError:
            logger.error("DeepSeek 聊天请求超时 (Circuit Breaker触发)")
            raise TimeoutError("大模型上游服务响应超时")
        except Exception as e:
            logger.error(f"DeepSeek 聊天请求失败: {e}")
            raise
        finally:
            await client.close()

    @staticmethod
    def _create_deepseek_client() -> AsyncOpenAI:
        """Use an explicit optional proxy; ignore broken ambient proxy variables."""
        proxy = (settings.DEEPSEEK_PROXY or "").strip() or None
        http_client = httpx.AsyncClient(
            proxies=proxy,
            trust_env=False,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        return AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
            http_client=http_client,
        )

    async def stream_chat_completion(
        self,
        messages: list[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天补全接口
        """
        provider = settings.LLM_PROVIDER
        if provider == LLMProvider.OPENAI:
            client = self.openai_client
            target_model = model or settings.OPENAI_MODEL
        elif provider == LLMProvider.DEEPSEEK:
            if not settings.DEEPSEEK_API_KEY:
                raise RuntimeError("DeepSeek API Key 未配置")
            client = self._create_deepseek_client()
            close_client = True
            target_model = model or settings.DEEPSEEK_MODEL
        else:
            raise ValueError(f"流式输出尚未支持 LLM 提供商: {provider}")

        if provider == LLMProvider.OPENAI:
            close_client = False
            
        if not client:
            raise RuntimeError(f"{provider} 客户端未初始化")

        try:
            # 开启 stream=True
            response_stream = await client.chat.completions.create(
                model=target_model,
                messages=messages,
                temperature=temperature,
                stream=True,
                **kwargs
            )
            async for chunk in response_stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"流式聊天请求失败: {e}")
            yield f"\n[后台报错: 流式输出异常 {str(e)}]"
        finally:
            if close_client:
                await client.close()


# 全局 LLM 配置实例
llm_config = LLMConfig()
