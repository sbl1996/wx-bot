import os
from typing import Optional, Dict
from datetime import datetime
from dataclasses import dataclass
import hashlib

from pydantic import BaseModel
from fastapi import FastAPI, Request, Response

from xml.etree.ElementTree import fromstring
from lxml import etree

from chat import Chat
import config

app = FastAPI()
app.user_states = {}


@dataclass
class UserState:
    chat: Chat = None
    last_visit_time: int = None


class RecvStandardMsg(BaseModel):
    URL: Optional[str]
    ToUserName: str
    FromUserName: str
    CreateTime: int
    MsgType: str
    Content: str
    MsgId: int


def check_weixin(signature, timestamp, nonce):
    """Checks if the provided signature, timestamp, and nonce are valid."""
    token = config.wechat_token
    list1 = [token, timestamp, nonce]
    list1.sort()
    list2 = [x.encode('utf-8') for x in list1]
    sha1 = hashlib.sha1()
    for x in list2:
        sha1.update(x)
    hashcode = sha1.hexdigest()
    return hashcode == signature


@app.get("/")
async def root(signature: str, echostr: str, timestamp: str, nonce: str) -> Response:
    if check_weixin(signature, timestamp, nonce):
        return Response(echostr)
    else:
        return Response("")


def parse_xml(xml_string):
    """Parses an XML string and returns a dictionary of tag-value pairs."""
    xml = fromstring(xml_string)
    children = list(xml)
    parsed = {}
    for x in children:
        parsed[x.tag] = x.text
    return parsed


# noinspection PyArgumentList
def xml_resp(recv_msg: RecvStandardMsg, text: str):
    """Creates an XML response for the given received message and text."""
    xml = etree.Element("xml")

    to_user_name = etree.SubElement(xml, "ToUserName")
    to_user_name.text = etree.CDATA(recv_msg.FromUserName)

    from_user_name = etree.SubElement(xml, "FromUserName")
    from_user_name.text = etree.CDATA(recv_msg.ToUserName)

    create_time = etree.SubElement(xml, "CreateTime")
    create_time.text = str(int(datetime.now().timestamp()))

    msg_type = etree.SubElement(xml, "MsgType")
    msg_type.text = etree.CDATA("text")

    content = etree.SubElement(xml, "Content")
    content.text = etree.CDATA(text)
    return etree.tounicode(xml)


# noinspection PyUnusedLocal
@app.post("/")
async def chat(req: Request, signature: str, timestamp: str, nonce: str, openid: str):
    """
    Handle incoming messages and respond with chatbot messages.

    :param req: The incoming HTTP request.
    :param signature: The signature from WeChat.
    :param timestamp: The timestamp from WeChat.
    :param nonce: The nonce from WeChat.
    :param openid: The ID of the user sending the message.
    :return: The HTTP response to send back to WeChat.
    """
    if not check_weixin(signature, timestamp, nonce):
        return Response("")

    # Parse the incoming message from XML to a Pydantic model.
    text = await req.body()
    msg = RecvStandardMsg.parse_obj(parse_xml(text))

    # Get the user state or create a new one if it doesn't exist.
    user_states: Dict[str, UserState] = req.app.user_states
    if msg.FromUserName not in user_states:
        user_states[msg.FromUserName] = UserState(Chat())
    state = user_states[msg.FromUserName]

    # Reset the chatbot if the user hasn't sent a message in the last 30 minutes.
    if state.last_visit_time is not None and (int(datetime.now().timestamp()) - state.last_visit_time) > (60 * 30):
        print("reset")
        state.chat = Chat()

    # Handle the "reset" command.
    if msg.Content.strip() == "reset":
        if state.last_visit_time is not None:
            state.chat = Chat()
        resp_text = "系统回复：对话已重置"
    else:
        # Send the user's message to the chatbot and get a response.
        # noinspection PyShadowingNames
        chat = state.chat
        chat_resp = await chat.send(msg.Content, msg.MsgId)
        resp_text = chat_resp.content
        # Handle the different response statuses from the chatbot.
        if chat_resp.status == 'wait':
            resp_text = "系统回复：服务器超时，5秒后回复“快”重试"
        elif chat_resp.status == 'error':
            resp_text = f"系统错误：{resp_text}"
        else:
            # Remove leading whitespace from the chatbot's response.
            resp_text = resp_text.lstrip()

            # Handle the case where the chatbot exceeds its maximum context length.
            if chat_resp.status == 'exceed':
                resp_text = f"{resp_text}\n\n总上下文长度超过3600词，已重置对话"
                state.chat = Chat()

    # Record the current time as the user's last visit time.
    state.last_visit_time = int(datetime.now().timestamp())

    # Convert the chatbot's response to XML and send it back to WeChat.
    return Response(xml_resp(msg, resp_text), media_type="text/xml")


@app.get("/wx")
async def wx(item):
    print("wx")
    print(item)
    return {"message": "Hello Weixin"}
