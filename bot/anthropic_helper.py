#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
anthropic_helper.py - Interfaccia con l'API di Anthropic Claude

Questo modulo gestisce tutte le interazioni con l'API di Anthropic Claude,
fornendo un'interfaccia strutturata per l'invio di richieste e l'elaborazione
delle risposte. Supporta sia l'elaborazione di testo che l'analisi di immagini.
"""

import os
import json
import base64
import logging
from typing import Dict, List, Optional, Union, Any, Literal, TypeVar, Generic
from enum import Enum
import asyncio
from io import BytesIO

import httpx
from pydantic import BaseModel, Field, validator
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ContentBlockParam, ImageBlockParam
from dotenv import load_dotenv

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Caricamento variabili d'ambiente
load_dotenv()

# Costanti
DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
API_KEY = os.getenv("ANTHROPIC_API_KEY")
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # secondi
MAX_TOKENS = 4096


class ClaudeModel(str, Enum):
    """Enumerazione dei modelli Claude supportati."""
    CLAUDE_3_5_SONNET = "claude-3-5-sonnet-20241022"
    CLAUDE_3_OPUS = "claude-3-opus-20240229"
    CLAUDE_3_HAIKU = "claude-3-haiku-20240307"
    CLAUDE_3_SONNET = "claude-3-sonnet-20240229"


class ContentBlockType(str, Enum):
    """Tipi di blocco di contenuto supportati."""
    TEXT = "text"
    IMAGE = "image"


class Role(str, Enum):
    """Ruoli possibili nei messaggi."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ImageFormat(str, Enum):
    """Formati di immagine supportati."""
    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"
    GIF = "gif"


class ImageBlock(BaseModel):
    """Rappresenta un blocco di immagine."""
    type: Literal["image"] = "image"
    source: Dict[str, Any]
    format: ImageFormat

    @validator('source')
    def validate_source(cls, v):
        if 'type' not in v or v['type'] not in ['base64']:
            raise ValueError("Il tipo di sorgente dell'immagine deve essere 'base64'")
        if 'data' not in v:
            raise ValueError("Mancano i dati dell'immagine")
        return v


class TextBlock(BaseModel):
    """Rappresenta un blocco di testo."""
    type: Literal["text"] = "text"
    text: str


class ContentBlock(BaseModel):
    """Un blocco di contenuto può essere testo o immagine."""
    __root__: Union[TextBlock, ImageBlock]

    def dict(self, **kwargs):
        if isinstance(self.__root__, TextBlock):
            return {"type": "text", "text": self.__root__.text}
        else:
            return self.__root__.dict(**kwargs)


class Message(BaseModel):
    """Rappresenta un messaggio nell'interazione con Claude."""
    role: Role
    content: List[Union[TextBlock, ImageBlock]]


class ToolCall(BaseModel):
    """Rappresenta una chiamata a uno strumento (tool)."""
    id: str
    type: str
    name: str
    input: Dict[str, Any]


class ToolOutput(BaseModel):
    """Rappresenta l'output di uno strumento."""
    tool_call_id: str
    output: Dict[str, Any]


class Tool(BaseModel):
    """Definizione di uno strumento che può essere chiamato da Claude."""
    name: str
    description: str
    input_schema: Dict[str, Any]


class ClaudeRequest(BaseModel):
    """Configurazione per una richiesta a Claude."""
    messages: List[Message]
    model: ClaudeModel = ClaudeModel.CLAUDE_3_5_SONNET
    max_tokens: int = MAX_TOKENS
    system: Optional[str] = None
    tools: Optional[List[Tool]] = None
    tool_outputs: Optional[List[ToolOutput]] = None
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    metadata: Optional[Dict[str, str]] = None


class ClaudeResponse(BaseModel):
    """Rappresenta la risposta da Claude."""
    id: str
    type: str
    role: Role
    content: List[Union[Dict[str, str], Dict[str, Dict]]]
    model: str
    stop_reason: Optional[str] = None
    stop_sequence: Optional[str] = None
    usage: Dict[str, int]
    tool_calls: Optional[List[ToolCall]] = None


class ClaudeException(Exception):
    """Eccezione personalizzata per errori relativi all'API di Claude."""
    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[Dict] = None):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)


class AnthropicHelper:
    """
    Classe principale per l'interfaccia con l'API di Anthropic Claude.
    Gestisce richieste, risposte e funzionalità avanzate come Vision.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        """
        Inizializza l'helper di Anthropic.
        
        Args:
            api_key: Chiave API di Anthropic (se None, usa la variabile d'ambiente)
            model: Modello Claude da utilizzare
        """
        self.api_key = api_key or API_KEY
        if not self.api_key:
            raise ValueError("API key di Anthropic non trovata. Impostala nell'ambiente o forniscila al costruttore.")
        
        self.model = model
        self.client = AsyncAnthropic(api_key=self.api_key)
        logger.info(f"AnthropicHelper inizializzato con modello: {self.model}")
    
    async def process_message(
        self,
        messages: List[Message],
        system: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        tool_outputs: Optional[List[ToolOutput]] = None,
        max_tokens: int = MAX_TOKENS,
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> ClaudeResponse:
        """
        Elabora un messaggio e ottiene una risposta da Claude.
        
        Args:
            messages: Lista di messaggi per la conversazione
            system: Messaggio di sistema opzionale
            tools: Lista di strumenti disponibili per Claude
            tool_outputs: Output degli strumenti da precedenti chiamate
            max_tokens: Numero massimo di token nella risposta
            temperature: Temperatura per la generazione (randomicità)
            model: Override del modello predefinito
            
        Returns:
            ClaudeResponse: La risposta elaborata di Claude
        """
        use_model = model or self.model
        
        # Conversione dei messaggi nel formato richiesto da Anthropic
        anthropic_messages = []
        for msg in messages:
            content_blocks = []
            for block in msg.content:
                if isinstance(block, TextBlock):
                    content_blocks.append({"type": "text", "text": block.text})
                elif isinstance(block, ImageBlock):
                    content_blocks.append({
                        "type": "image",
                        "source": block.source,
                        "format": block.format
                    })
            
            anthropic_messages.append({
                "role": msg.role,
                "content": content_blocks
            })
        
        # Preparazione degli strumenti se presenti
        anthropic_tools = None
        if tools:
            anthropic_tools = [tool.dict() for tool in tools]
        
        # Preparazione degli output degli strumenti se presenti
        anthropic_tool_outputs = None
        if tool_outputs:
            anthropic_tool_outputs = [output.dict() for output in tool_outputs]
        
        try:
            for attempt in range(MAX_RETRIES):
                try:
                    # Invio della richiesta a Claude
                    response = await self.client.messages.create(
                        model=use_model,
                        messages=anthropic_messages,
                        system=system,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        tools=anthropic_tools,
                        tool_outputs=anthropic_tool_outputs
                    )
                    
                    # Conversione della risposta in un oggetto ClaudeResponse
                    return ClaudeResponse(
                        id=response.id,
                        type=response.type,
                        role=response.role,
                        content=response.content,
                        model=response.model,
                        stop_reason=response.stop_reason,
                        stop_sequence=response.stop_sequence,
                        usage=response.usage,
                        tool_calls=response.tool_calls if hasattr(response, 'tool_calls') else None
                    )
                    
                except httpx.TimeoutException:
                    if attempt < MAX_RETRIES - 1:
                        logger.warning(f"Timeout durante la richiesta a Claude. Tentativo {attempt+1}/{MAX_RETRIES}. Riprovo...")
                        await asyncio.sleep(RETRY_DELAY * (2 ** attempt))  # Exponential backoff
                    else:
                        raise ClaudeException("Timeout durante la richiesta a Claude dopo diversi tentativi.")
                        
                except httpx.HTTPStatusError as e:
                    if e.response.status_code >= 500 and attempt < MAX_RETRIES - 1:
                        logger.warning(f"Errore server {e.response.status_code}. Tentativo {attempt+1}/{MAX_RETRIES}. Riprovo...")
                        await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
                    else:
                        raise ClaudeException(
                            f"Errore HTTP durante la richiesta a Claude: {str(e)}",
                            status_code=e.response.status_code,
                            response=e.response.json() if e.response.content else None
                        )
                        
        except Exception as e:
            logger.error(f"Errore durante l'elaborazione della richiesta a Claude: {str(e)}")
            raise ClaudeException(f"Errore durante l'elaborazione della richiesta a Claude: {str(e)}")
    
    async def simple_query(self, text: str, system: Optional[str] = None, model: Optional[str] = None) -> str:
        """
        Metodo semplificato per inviare una query di solo testo a Claude.
        
        Args:
            text: Testo della query
            system: Messaggio di sistema opzionale
            model: Override del modello predefinito
            
        Returns:
            str: Testo della risposta di Claude
        """
        messages = [
            Message(
                role=Role.USER,
                content=[TextBlock(text=text)]
            )
        ]
        
        response = await self.process_message(
            messages=messages,
            system=system,
            model=model or self.model
        )
        
        # Estrai il testo dalla risposta
        text_content = ""
        for block in response.content:
            if block.get('type') == 'text':
                text_content += block.get('text', '')
        
        return text_content
    
    @staticmethod
    def encode_image(image_data: Union[bytes, BytesIO], format: str = "jpeg") -> Dict[str, Any]:
        """
        Codifica un'immagine in Base64 per l'invio a Claude Vision.
        
        Args:
            image_data: Dati dell'immagine come bytes o BytesIO
            format: Formato dell'immagine (jpeg, png, webp, gif)
            
        Returns:
            Dict: Dizionario con i dati dell'immagine codificati
        """
        if isinstance(image_data, BytesIO):
            image_bytes = image_data.getvalue()
        else:
            image_bytes = image_data
            
        base64_data = base64.b64encode(image_bytes).decode('utf-8')
        
        return {
            "type": "base64",
            "data": base64_data
        }
    
    async def analyze_image(
        self,
        image_data: Union[bytes, BytesIO],
        query: str,
        image_format: str = "jpeg",
        system: Optional[str] = None,
        model: Optional[str] = None
    ) -> str:
        """
        Analizza un'immagine usando Claude Vision.
        
        Args:
            image_data: Dati dell'immagine come bytes o BytesIO
            query: Domanda o istruzione relativa all'immagine
            image_format: Formato dell'immagine (jpeg, png, webp, gif)
            system: Messaggio di sistema opzionale
            model: Override del modello predefinito
            
        Returns:
            str: Testo della risposta di Claude Vision
        """
        # Codifica l'immagine
        encoded_image = self.encode_image(image_data, image_format)
        
        # Crea il messaggio con testo e immagine
        messages = [
            Message(
                role=Role.USER,
                content=[
                    ImageBlock(
                        source=encoded_image,
                        format=ImageFormat(image_format)
                    ),
                    TextBlock(text=query)
                ]
            )
        ]
        
        # Invia la richiesta
        response = await self.process_message(
            messages=messages,
            system=system,
            model=model or self.model
        )
        
        # Estrai il testo dalla risposta
        text_content = ""
        for block in response.content:
            if block.get('type') == 'text':
                text_content += block.get('text', '')
        
        return text_content
    
    async def process_with_tools(
        self,
        query: str,
        tools: List[Tool],
        tool_outputs: Optional[List[ToolOutput]] = None,
        system: Optional[str] = None,
        model: Optional[str] = None
    ) -> ClaudeResponse:
        """
        Elabora una query con strumenti disponibili per Claude.
        
        Args:
            query: Testo della query
            tools: Lista di strumenti disponibili
            tool_outputs: Output degli strumenti da precedenti chiamate
            system: Messaggio di sistema opzionale
            model: Override del modello predefinito
            
        Returns:
            ClaudeResponse: La risposta elaborata di Claude con eventuali chiamate a strumenti
        """
        messages = [
            Message(
                role=Role.USER,
                content=[TextBlock(text=query)]
            )
        ]
        
        return await self.process_message(
            messages=messages,
            system=system,
            tools=tools,
            tool_outputs=tool_outputs,
            model=model or self.model
        )


# Funzioni di utilità

async def test_connection(api_key: Optional[str] = None) -> bool:
    """
    Testa la connessione all'API di Anthropic.
    
    Args:
        api_key: Chiave API di Anthropic (se None, usa la variabile d'ambiente)
        
    Returns:
        bool: True se la connessione è riuscita, False altrimenti
    """
    try:
        helper = AnthropicHelper(api_key=api_key)
        response = await helper.simple_query("Ciao, sei online?")
        return True
    except Exception as e:
        logger.error(f"Errore durante il test di connessione: {str(e)}")
        return False


async def get_available_models(api_key: Optional[str] = None) -> List[str]:
    """
    Ottiene la lista dei modelli disponibili.
    
    Args:
        api_key: Chiave API di Anthropic (se None, usa la variabile d'ambiente)
        
    Returns:
        List[str]: Lista dei modelli disponibili
    """
    # Nota: Anthropic non ha un endpoint specifico per ottenere i modelli disponibili
    # Questa è una lista statica che potrebbe richiedere aggiornamenti manuali
    return [model.value for model in ClaudeModel]


if __name__ == "__main__":
    """Test di base del modulo."""
    async def run_test():
        try:
            print("Testando la connessione all'API di Anthropic...")
            connection_ok = await test_connection()
            if connection_ok:
                print("✅ Connessione riuscita!")
                print(f"Modelli disponibili: {await get_available_models()}")
                
                helper = AnthropicHelper()
                response = await helper.simple_query("Quali sono le principali funzionalità di un assistente per la gestione di piani alimentari?")
                print("\nRisposta di Claude:")
                print(response)
            else:
                print("❌ Test di connessione fallito.")
        except Exception as e:
            print(f"❌ Errore durante il test: {str(e)}")
    
    # Esegui il test asincrono
    asyncio.run(run_test())
