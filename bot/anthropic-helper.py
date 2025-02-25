from __future__ import annotations
import datetime
import logging
import os
import json
import httpx
import io
from PIL import Image

from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from anthropic import AsyncAnthropic, RateLimitError, BadRequestError
from anthropic.types import MessageParam

from utils import is_direct_result, encode_image, decode_image
from plugin_manager import PluginManager

# Modelli Claude disponibili
CLAUDE_3_MODELS = ("claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307")
CLAUDE_3_5_MODELS = ("claude-3-5-sonnet-20240307",)
CLAUDE_INSTANT_MODELS = ("claude-instant-1.2",)
CLAUDE_2_MODELS = ("claude-2.0", "claude-2.1")
CLAUDE_ALL_MODELS = CLAUDE_3_MODELS + CLAUDE_3_5_MODELS + CLAUDE_INSTANT_MODELS + CLAUDE_2_MODELS

def default_max_tokens(model: str) -> int:
    """
    Gets the default number of max tokens for the given model.
    :param model: The model name
    :return: The default number of max tokens
    """
    if model in CLAUDE_3_MODELS:
        return 4096
    elif model in CLAUDE_3_5_MODELS:
        return 4096
    elif model in CLAUDE_INSTANT_MODELS:
        return 2000
    elif model in CLAUDE_2_MODELS:
        return 2000
    else:
        return 2000  # Default value for unknown models

def are_functions_available(model: str) -> bool:
    """
    Whether the given model supports functions/tools
    """
    # Claude 3 models support tools
    if model in CLAUDE_3_MODELS or model in CLAUDE_3_5_MODELS:
        return True
    return False

# Load translations
parent_dir_path = os.path.join(os.path.dirname(__file__), os.pardir)
translations_file_path = os.path.join(parent_dir_path, 'translations.json')
with open(translations_file_path, 'r', encoding='utf-8') as f:
    translations = json.load(f)

def localized_text(key, bot_language):
    """
    Return translated text for a key in specified bot_language.
    Keys and translations can be found in the translations.json.
    """
    try:
        return translations[bot_language][key]
    except KeyError:
        logging.warning(f"No translation available for bot_language code '{bot_language}' and key '{key}'")
        # Fallback to English if the translation is not available
        if key in translations['en']:
            return translations['en'][key]
        else:
            logging.warning(f"No english definition found for key '{key}' in translations.json")
            # return key as text
            return key

class AnthropicHelper:
    """
    Claude helper class.
    """

    def __init__(self, config: dict, plugin_manager: PluginManager):
        """
        Initializes the Anthropic helper class with the given configuration.
        :param config: A dictionary containing the Claude configuration
        :param plugin_manager: The plugin manager
        """
        http_client = httpx.AsyncClient(proxy=config['proxy']) if 'proxy' in config else None
        self.client = AsyncAnthropic(api_key=config['api_key'], http_client=http_client)
        self.config = config
        self.plugin_manager = plugin_manager
        self.conversations: dict[int: list] = {}  # {chat_id: history}
        self.conversations_vision: dict[int: bool] = {}  # {chat_id: is_vision}
        self.last_updated: dict[int: datetime] = {}  # {chat_id: last_update_timestamp}

    def get_conversation_stats(self, chat_id: int) -> tuple[int, int]:
        """
        Gets the number of messages and tokens used in the conversation.
        :param chat_id: The chat ID
        :return: A tuple containing the number of messages and tokens used
        """
        if chat_id not in self.conversations:
            self.reset_chat_history(chat_id)
        return len(self.conversations[chat_id]), self.__estimate_tokens(self.conversations[chat_id])

    async def get_chat_response(self, chat_id: int, query: str) -> tuple[str, str]:
        """
        Gets a full response from the Claude model.
        :param chat_id: The chat ID
        :param query: The query to send to the model
        :return: The answer from the model and the number of tokens used
        """
        plugins_used = ()
        response = await self.__common_get_chat_response(chat_id, query)
        
        # If tools are enabled and model supports them
        if self.config['enable_functions'] and are_functions_available(self.config['model']) and not self.conversations_vision[chat_id]:
            response, plugins_used = await self.__handle_function_call(chat_id, response)
            if is_direct_result(response):
                return response, '0'

        answer = response.content[0].text
        self.__add_to_history(chat_id, role="assistant", content=answer)

        bot_language = self.config['bot_language']
        show_plugins_used = len(plugins_used) > 0 and self.config['show_plugins_used']
        plugin_names = tuple(self.plugin_manager.get_plugin_source_name(plugin) for plugin in plugins_used)
        
        # Estimate token usage
        total_tokens = self.__estimate_tokens(self.conversations[chat_id])
        prompt_tokens = total_tokens // 2  # Rough estimate
        completion_tokens = total_tokens - prompt_tokens
        
        if self.config['show_usage']:
            answer += "\n\n---\n" \
                      f"💰 {str(total_tokens)} {localized_text('stats_tokens', bot_language)}" \
                      f" ({str(prompt_tokens)} {localized_text('prompt', bot_language)}," \
                      f" {str(completion_tokens)} {localized_text('completion', bot_language)})"
            if show_plugins_used:
                answer += f"\n🔌 {', '.join(plugin_names)}"
        elif show_plugins_used:
            answer += f"\n\n---\n🔌 {', '.join(plugin_names)}"

        return answer, str(total_tokens)

    async def get_chat_response_stream(self, chat_id: int, query: str):
        """
        Stream response from the Claude model.
        :param chat_id: The chat ID
        :param query: The query to send to the model
        :return: The answer from the model and the number of tokens used, or 'not_finished'
        """
        plugins_used = ()
        response = await self.__common_get_chat_response(chat_id, query, stream=True)
        
        if self.config['enable_functions'] and are_functions_available(self.config['model']) and not self.conversations_vision[chat_id]:
            # Non-streaming function call handling for now
            # This is a simplification as streaming with tools is more complex
            final_response = await self.__common_get_chat_response(chat_id, query, stream=False)
            final_response, plugins_used = await self.__handle_function_call(chat_id, final_response)
            if is_direct_result(final_response):
                yield final_response, '0'
                return
            
            answer = final_response.content[0].text
            self.__add_to_history(chat_id, role="assistant", content=answer)
            tokens_used = str(self.__estimate_tokens(self.conversations[chat_id]))
            
            show_plugins_used = len(plugins_used) > 0 and self.config['show_plugins_used']
            plugin_names = tuple(self.plugin_manager.get_plugin_source_name(plugin) for plugin in plugins_used)
            
            if self.config['show_usage']:
                answer += f"\n\n---\n💰 {tokens_used} {localized_text('stats_tokens', self.config['bot_language'])}"
                if show_plugins_used:
                    answer += f"\n🔌 {', '.join(plugin_names)}"
            elif show_plugins_used:
                answer += f"\n\n---\n🔌 {', '.join(plugin_names)}"
            
            yield answer, tokens_used
            return

        # Regular streaming without function calls
        answer = ""
        async for text_delta in self.__process_streaming_response(response):
            if text_delta:
                answer += text_delta
                yield answer, 'not_finished'
        
        answer = answer.strip()
        self.__add_to_history(chat_id, role="assistant", content=answer)
        tokens_used = str(self.__estimate_tokens(self.conversations[chat_id]))

        if self.config['show_usage']:
            answer += f"\n\n---\n💰 {tokens_used} {localized_text('stats_tokens', self.config['bot_language'])}"

        yield answer, tokens_used

    async def __process_streaming_response(self, stream):
        """
        Process a streaming response from Anthropic
        """
        async for chunk in stream:
            if hasattr(chunk, 'delta') and chunk.delta.text:
                yield chunk.delta.text
            elif hasattr(chunk, 'content') and chunk.content:
                for content_item in chunk.content:
                    if hasattr(content_item, 'text'):
                        yield content_item.text

    @retry(
        reraise=True,
        retry=retry_if_exception_type(RateLimitError),
        wait=wait_fixed(20),
        stop=stop_after_attempt(3)
    )
    async def __common_get_chat_response(self, chat_id: int, query: str, stream=False):
        """
        Request a response from the Claude model.
        :param chat_id: The chat ID
        :param query: The query to send to the model
        :param stream: Whether to stream the response
        :return: The answer from the model
        """
        bot_language = self.config['bot_language']
        try:
            if chat_id not in self.conversations or self.__max_age_reached(chat_id):
                self.reset_chat_history(chat_id)

            self.last_updated[chat_id] = datetime.datetime.now()

            # Add user message to conversation history
            self.__add_to_history(chat_id, role="user", content=query)

            # Summarize the chat history if it's too long to avoid excessive token usage
            conversation_length = len(self.conversations[chat_id])
            exceeded_max_history_size = conversation_length > self.config['max_history_size']
            estimated_tokens = self.__estimate_tokens(self.conversations[chat_id])
            exceeded_max_tokens = estimated_tokens > 100000  # Claude has high token limits, but set a reasonable cap

            if exceeded_max_tokens or exceeded_max_history_size:
                logging.info(f'Chat history for chat ID {chat_id} is too long. Summarising...')
                try:
                    summary = await self.__summarise(self.conversations[chat_id][:-1])
                    logging.debug(f'Summary: {summary}')
                    self.reset_chat_history(chat_id, self.conversations[chat_id][0]['content'])
                    self.__add_to_history(chat_id, role="assistant", content=summary)
                    self.__add_to_history(chat_id, role="user", content=query)
                except Exception as e:
                    logging.warning(f'Error while summarising chat history: {str(e)}. Popping elements instead...')
                    self.conversations[chat_id] = self.conversations[chat_id][-self.config['max_history_size']:]

            # Convert conversation history to Anthropic format
            messages = self.__convert_to_anthropic_messages(self.conversations[chat_id])

            # Set parameters
            max_tokens = self.config.get('max_tokens', default_max_tokens(self.config['model']))
            temperature = self.config.get('temperature', 1.0)
            model = self.config.get('model', 'claude-3-sonnet-20240229')
            
            # Build message parameters
            message_params = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": stream
            }
            
            # Add system prompt if it exists
            system_prompt = self.config.get('assistant_prompt', 'You are a helpful assistant.')
            if system_prompt:
                message_params["system"] = system_prompt
                
            # Enable tools if supported and requested
            if self.config['enable_functions'] and are_functions_available(model):
                tools = self.__convert_to_anthropic_tools()
                if tools:
                    message_params["tools"] = tools

            # Call Anthropic API
            return await self.client.messages.create(**message_params)

        except RateLimitError as e:
            raise e
        except BadRequestError as e:
            raise Exception(f"⚠️ _{localized_text('openai_invalid', bot_language)}._ ⚠️\n{str(e)}") from e
        except Exception as e:
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    def __convert_to_anthropic_messages(self, conversation_history):
        """Convert internal conversation history format to Anthropic's message format"""
        messages = []
        
        for message in conversation_history:
            role = message["role"]
            content = message["content"]
            
            # Skip system messages as they're handled separately
            if role == "system":
                continue
                
            # Map OpenAI roles to Anthropic roles
            if role == "function":
                # Handle function messages as assistant messages with metadata
                messages.append({
                    "role": "assistant",
                    "content": [{"type": "text", "text": f"Function result: {content}"}]
                })
            else:
                # Handle regular messages
                if isinstance(content, str):
                    messages.append({
                        "role": "assistant" if role == "assistant" else "user",
                        "content": [{"type": "text", "text": content}]
                    })
                elif isinstance(content, list):
                    # Handle messages with mixed content (text and images)
                    anthropic_content = []
                    for item in content:
                        if item["type"] == "text":
                            anthropic_content.append({"type": "text", "text": item["text"]})
                        elif item["type"] == "image_url":
                            image_data = item["image_url"]["url"].split(",")[1]
                            anthropic_content.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_data
                                }
                            })
                    messages.append({
                        "role": "assistant" if role == "assistant" else "user",
                        "content": anthropic_content
                    })
        
        return messages

    def __convert_to_anthropic_tools(self):
        """Convert plugin functions to Anthropic tool format"""
        if not self.plugin_manager:
            return None
            
        functions = self.plugin_manager.get_functions_specs()
        if not functions:
            return None
            
        tools = []
        
        for function in functions:
            tool = {
                "name": function["name"],
                "description": function.get("description", ""),
                "input_schema": function.get("parameters", {})
            }
            tools.append({"function": tool})
            
        return tools

    async def __handle_function_call(self, chat_id, response, times=0, plugins_used=()):
        """
        Handle Anthropic tool/function calls
        """
        # Check if the response contains a tool call
        if not hasattr(response, 'content') or not response.content:
            return response, plugins_used
            
        for content_item in response.content:
            if hasattr(content_item, 'type') and content_item.type == 'tool_use':
                # Extract tool info
                tool_name = content_item.tool_use.name
                tool_args = content_item.tool_use.input
                
                logging.info(f'Calling function {tool_name} with arguments {tool_args}')
                
                # Call function
                function_response = await self.plugin_manager.call_function(
                    tool_name, 
                    self, 
                    json.dumps(tool_args)
                )
                
                if tool_name not in plugins_used:
                    plugins_used += (tool_name,)
                
                if is_direct_result(function_response):
                    self.__add_function_call_to_history(
                        chat_id=chat_id, 
                        function_name=tool_name,
                        content=json.dumps({'result': 'Done, the content has been sent to the user.'})
                    )
                    return function_response, plugins_used
                
                # Add function call result to history
                self.__add_function_call_to_history(
                    chat_id=chat_id, 
                    function_name=tool_name, 
                    content=function_response
                )
                
                # Get Claude's response to the function result
                if times < self.config['functions_max_consecutive_calls']:
                    # Convert history to Anthropic format
                    messages = self.__convert_to_anthropic_messages(self.conversations[chat_id])
                    
                    # Call Claude again with the updated history
                    response = await self.client.messages.create(
                        model=self.config['model'],
                        messages=messages,
                        system=self.config.get('assistant_prompt', 'You are a helpful assistant.'),
                        tools=self.__convert_to_anthropic_tools() if self.config['enable_functions'] else None,
                        max_tokens=self.config.get('max_tokens', default_max_tokens(self.config['model'])),
                        temperature=self.config.get('temperature', 1.0)
                    )
                    
                    # Recursively handle any further tool calls
                    return await self.__handle_function_call(chat_id, response, times + 1, plugins_used)
        
        # No tool calls or max recursive depth reached
        return response, plugins_used

    async def generate_image(self, prompt: str) -> tuple[str, str]:
        """
        Claude doesn't have native image generation - inform the user
        """
        bot_language = self.config['bot_language']
        raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n" +
                       "Claude does not support image generation. Please use a different service for generating images.")

    async def generate_speech(self, text: str) -> tuple[any, int]:
        """
        Claude doesn't have native TTS - inform the user
        """
        bot_language = self.config['bot_language']
        raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n" +
                       "Claude does not support text-to-speech. Please use a different service for TTS.")

    async def transcribe(self, filename):
        """
        Claude doesn't have native transcription - inform the user
        """
        bot_language = self.config['bot_language']
        raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n" +
                       "Claude does not support audio transcription. Please use a different service for transcription.")

    async def interpret_image(self, chat_id, fileobj, prompt=None):
        """
        Interprets a given image file using Claude's vision capabilities.
        """
        # Use default prompt if none provided
        prompt = self.config['vision_prompt'] if prompt is None else prompt
        
        # Encode the image to base64
        image_base64 = encode_image(fileobj)
        
        # Create content with prompt and image
        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_base64.split(",")[1]  # Remove data:image/jpeg;base64, prefix
                }
            }
        ]
        
        # Set vision flag
        self.conversations_vision[chat_id] = True
        
        # Add to history
        self.__add_to_history(chat_id, role="user", content=content)
        
        # Create message parameters
        message_params = {
            "model": self.config['vision_model'],
            "messages": self.__convert_to_anthropic_messages(self.conversations[chat_id]),
            "max_tokens": self.config.get('vision_max_tokens', 300),
            "temperature": self.config.get('temperature', 1.0),
            "system": self.config.get('assistant_prompt', 'You are a helpful assistant.')
        }
        
        # Call Claude API
        try:
            response = await self.client.messages.create(**message_params)
            
            answer = response.content[0].text
            self.__add_to_history(chat_id, role="assistant", content=answer)
            
            # Estimate token usage
            total_tokens = self.__estimate_tokens(self.conversations[chat_id])
            
            bot_language = self.config['bot_language']
            if self.config['show_usage']:
                answer += f"\n\n---\n💰 {str(total_tokens)} {localized_text('stats_tokens', bot_language)}"
            
            return answer, total_tokens
            
        except Exception as e:
            bot_language = self.config['bot_language']
            raise Exception(f"⚠️ _{localized_text('vision_fail', bot_language)}._ ⚠️\n{str(e)}") from e

    async def interpret_image_stream(self, chat_id, fileobj, prompt=None):
        """
        Interprets a given image file using Claude's vision capabilities with streaming.
        """
        # Vision calls often can't be streamed effectively with anthropic's API
        # So we'll use non-streaming call and return it all at once
        answer, total_tokens = await self.interpret_image(chat_id, fileobj, prompt)
        yield answer, str(total_tokens)

    def reset_chat_history(self, chat_id, content=''):
        """
        Resets the conversation history.
        """
        if content == '':
            content = self.config['assistant_prompt']
        self.conversations[chat_id] = [{"role": "system", "content": content}]
        self.conversations_vision[chat_id] = False

    def __max_age_reached(self, chat_id) -> bool:
        """
        Checks if the maximum conversation age has been reached.
        :param chat_id: The chat ID
        :return: A boolean indicating whether the maximum conversation age has been reached
        """
        if chat_id not in self.last_updated:
            return False
        last_updated = self.last_updated[chat_id]
        now = datetime.datetime.now()
        max_age_minutes = self.config['max_conversation_age_minutes']
        return last_updated < now - datetime.timedelta(minutes=max_age_minutes)

    def __add_function_call_to_history(self, chat_id, function_name, content):
        """
        Adds a function call to the conversation history
        """
        self.conversations[chat_id].append({"role": "function", "name": function_name, "content": content})

    def __add_to_history(self, chat_id, role, content):
        """
        Adds a message to the conversation history.
        :param chat_id: The chat ID
        :param role: The role of the message sender
        :param content: The message content
        """
        self.conversations[chat_id].append({"role": role, "content": content})

    async def __summarise(self, conversation) -> str:
        """
        Summarises the conversation history using Claude.
        :param conversation: The conversation history
        :return: The summary
        """
        # Convert conversation to Anthropic format
        anthropic_messages = self.__convert_to_anthropic_messages(conversation)
        
        # Add a summarization request
        anthropic_messages.append({
            "role": "user",
            "content": [{"type": "text", "text": "Please summarize our conversation so far in 700 characters or less."}]
        })
        
        # Call Claude API
        response = await self.client.messages.create(
            model=self.config['model'],
            messages=anthropic_messages,
            max_tokens=1000,
            temperature=0.3
        )
        
        return response.content[0].text

    def __estimate_tokens(self, messages) -> int:
        """
        Estimates the number of tokens in the conversation.
        This is a rough estimate as Claude doesn't have a token counting API.
        :param messages: The conversation history
        :return: Estimated token count
        """
        total_chars = 0
        
        for message in messages:
            content = message["content"]
            
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        total_chars += len(item.get("text", ""))
                    # Images are counted differently but we'll add a fixed amount
                    elif item.get("type") == "image" or item.get("type") == "image_url":
                        total_chars += 1000  # Rough estimate for an image
        
        # Very rough estimate: 1 token ≈ 4 characters for English text
        return total_chars // 4
