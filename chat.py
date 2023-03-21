import logging
from dataclasses import dataclass

import asyncio
import httpx

import config

chat_url = 'https://api.openai.com/v1/chat/completions'
chat_url_free = "https://chatgpt-api.shn.hk/v1/"

api_key = config.api_key
proxy_url = config.proxy_url


@dataclass
class ChatResponse:
    content: str = None
    # success, wait, exceed, error
    status: str = 'success'


async def create_chat(messages, model='gpt-3.5-turbo', free=False):
    if free:
        url = chat_url_free
        headers = None
        proxy = None
    else:
        url = chat_url
        headers = {'Authorization': 'Bearer ' + api_key}
        proxy = proxy_url
    data = {'model': model, 'messages': messages}
    client = httpx.AsyncClient(proxies=proxy, headers=headers, timeout=30)
    resp = await client.post(url, json=data)
    json = resp.json()
    total_tokens = json['usage']['total_tokens']
    content = json['choices'][0]['message']['content']
    if total_tokens > 3600:
        return ChatResponse(content, status='exceed')
    else:
        return ChatResponse(content)

    # n = random.randint(1, 12)
    # client = httpx.AsyncClient(timeout=30)
    # resp = await client.get("http://127.0.0.1:8081/sleep/" + str(n))

    # text = ":".join([
    #     m['content'][:2] for m in messages if m['role'] == 'user'
    # ])
    # return text


class Chat:

    def __init__(self, model='gpt-3.5-turbo') -> None:
        self.model = model
        self._history = []
        self._prev_msg_id = None
        self._queue = asyncio.Queue()
        # idle, busy
        self._status = 'idle'
        self._n_wait = 0

    async def send(self, content, msg_id=None, timeout=4) -> ChatResponse:
        if self._status == 'idle':
            asyncio.create_task(self._send(content, msg_id))
            try:
                result = await asyncio.wait_for(self._queue.get(), timeout)
                return result
            except asyncio.exceptions.TimeoutError:
                self._status = 'busy'
                return ChatResponse(status='wait')
        elif self._status == 'busy':
            if self._n_wait != 0:
                return ChatResponse(status='wait')
            try:
                self._n_wait += 1
                result = await asyncio.wait_for(self._queue.get(), timeout)
                self._status = 'idle'
                self._n_wait = 0
                return result
            except asyncio.exceptions.TimeoutError:
                self._n_wait -= 1
                return ChatResponse(status='wait')
        else:
            # unreachable
            logging.error('Unknown status')
            return ChatResponse("内部状态错误，请联系管理员", status='error')

    async def _send(self, content, msg_id=None):
        user_msg = {"role": "user", "content": content}
        messages = [*self._history, user_msg]
        try:
            chat_resp = await create_chat(messages, self.model)
            resp_content = chat_resp.content
            self._history.append(user_msg)
            self._history.append({'role': 'assistant', 'content': resp_content})
            self._prev_msg_id = msg_id
            self._queue.put_nowait(chat_resp)
        except httpx.TimeoutException:
            self._queue.put_nowait(
                ChatResponse('API调用超时，请稍后再试', status='error'))
        except Exception as e:
            logging.error(e)
            self._queue.put_nowait(
                ChatResponse('API调用错误，请稍后再试', status='error'))
