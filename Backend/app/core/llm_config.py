"""
大语言模型配置管理器
支持 OpenAI、智谱AI、DeepSeek 等
"""

import logging
from typing import Optional, Dict, Any, AsyncGenerator
from enum import Enum
import asyncio

from fastapi import HTTPException
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
            self.openai_client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                http_client=httpx.AsyncClient(
                    timeout=60.0,
                    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                )
            )
            logger.info("OpenAI 客户端初始化成功")
        else:
            logger.warning("OpenAI API Key 未配置，部分功能可能不可用")

        # 设置 Embedding 提供商
        if settings.LLM_PROVIDER == LLMProvider.ZHIPU:
            self.embedding_provider = EmbeddingProvider.ZHIPU
        elif settings.LLM_PROVIDER == LLMProvider.DEEPSEEK:
            self.embedding_provider = EmbeddingProvider.OPENAI  # DeepSeek 使用 OpenAI 兼容接口
        else:
            self.embedding_provider = EmbeddingProvider.OPENAI

    def get_openai_client(self) -> AsyncOpenAI:
        """获取 OpenAI 客户端"""
        if not self.openai_client:
            raise RuntimeError("OpenAI 客户端未初始化")
        return self.openai_client

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

    async def chat_completion(
        self,
        messages: list[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
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

        if provider == LLMProvider.OPENAI:
            return await self._openai_chat_completion(messages, model, temperature, **kwargs)
        elif provider == LLMProvider.ZHIPU:
            return await self._zhipu_chat_completion(messages, model, temperature, **kwargs)
        elif provider == LLMProvider.DEEPSEEK:
            return await self._deepseek_chat_completion(messages, model, temperature, **kwargs)
        else:
            raise ValueError(f"不支持的 LLM 提供商: {provider}")

    async def _openai_chat_completion(
        self,
        messages: list[Dict[str, str]],
        model: Optional[str],
        temperature: float,
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
            response = await asyncio.wait_for(coro, timeout=30.0)
            return response.choices[0].message.content
        except asyncio.TimeoutError:
            logger.error("OpenAI 聊天请求超时 (Circuit Breaker触发)")
            raise HTTPException(status_code=504, detail="大模型上游服务响应超时")
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
        **kwargs
    ) -> str:
        """DeepSeek 聊天补全"""
        if not settings.DEEPSEEK_API_KEY:
            raise RuntimeError("DeepSeek API Key 未配置")

        # DeepSeek 使用 OpenAI 兼容接口
        try:
            client = AsyncOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
            )

            coro = client.chat.completions.create(
                model=model or settings.DEEPSEEK_MODEL,
                messages=messages,
                temperature=temperature,
                **kwargs
            )
            response = await asyncio.wait_for(coro, timeout=30.0)
            return response.choices[0].message.content
        except asyncio.TimeoutError:
            logger.error("DeepSeek 聊天请求超时 (Circuit Breaker触发)")
            from fastapi import HTTPException
            raise HTTPException(status_code=504, detail="大模型上游服务响应超时")
        except Exception as e:
            logger.error(f"DeepSeek 聊天请求失败: {e}")
            raise

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
            client = AsyncOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
            )
            target_model = model or settings.DEEPSEEK_MODEL
        else:
            raise ValueError(f"流式输出尚未支持 LLM 提供商: {provider}")
            
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


# 全局 LLM 配置实例
llm_config = LLMConfig()