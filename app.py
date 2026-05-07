import os
import time
import base64
import hashlib
import struct
import threading
import xml.etree.ElementTree as ET

import requests
from flask import Flask, request, jsonify
from Crypto.Cipher import AES


app = Flask(__name__)

TOKEN_CACHE = {
    "access_token": "",
    "expire_at": 0,
}

RECENT_MSG_IDS = {}


# =============================
# 基础工具
# =============================

def get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_exists(name: str) -> bool:
    return bool(get_env(name))


def now_ts() -> int:
    return int(time.time())


def build_chat_url(raw_url: str) -> str:
    """
    兼容两种 MID_API_URL 填法：

    1. https://chunfeng.mentalout.top
    2. https://chunfeng.mentalout.top/v1/chat/completions
    """
    url = raw_url.strip().rstrip("/")

    if url.endswith("/v1/chat/completions"):
        return url

    if url.endswith("/v1"):
        return url + "/chat/completions"

    return url + "/v1/chat/completions"


def split_text(text: str, limit: int = 1800):
    text = text or ""
    return [text[i:i + limit] for i in range(0, len(text), limit)] or [""]


def is_duplicate_msg(msg_id: str, ttl: int = 600) -> bool:
    if not msg_id:
        return False

    current = now_ts()

    expired = [
        key for key, saved_at in RECENT_MSG_IDS.items()
        if current - saved_at > ttl
    ]
    for key in expired:
        RECENT_MSG_IDS.pop(key, None)

    if msg_id in RECENT_MSG_IDS:
        return True

    RECENT_MSG_IDS[msg_id] = current
    return False


# =============================
# 企业微信加解密
# =============================

def sha1_signature(token: str, timestamp: str, nonce: str, encrypted: str) -> str:
    items = [token, timestamp, nonce, encrypted]
    items.sort()
    raw = "".join(items).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("empty decrypted data")

    pad = data[-1]

    if pad < 1 or pad > 32:
        raise ValueError(f"invalid padding: {pad}")

    return data[:-pad]


def get_aes_key() -> bytes:
    aes_key = get_env("WECHAT_AES_KEY")

    if not aes_key:
        raise ValueError("WECHAT_AES_KEY is not configured")

    if len(aes_key) != 43:
        raise ValueError("WECHAT_AES_KEY length must be 43")

    return base64.b64decode(aes_key + "=")


def decrypt_wechat_message(encrypted: str) -> str:
    """
    解密企业微信 Encrypt 字段，返回明文 XML 或 echostr 明文。
    """
    corp_id = get_env("CORP_ID")
    aes_key = get_aes_key()

    cipher = AES.new(aes_key, AES.MODE_CBC, aes_key[:16])
    encrypted_bytes = base64.b64decode(encrypted)
    decrypted = cipher.decrypt(encrypted_bytes)
    decrypted = pkcs7_unpad(decrypted)

    if len(decrypted) < 20:
        raise ValueError("decrypted data too short")

    msg_len = struct.unpack("!I", decrypted[16:20])[0]
    msg = decrypted[20:20 + msg_len].decode("utf-8")
    receive_id = decrypted[20 + msg_len:].decode("utf-8")

    if corp_id and receive_id and receive_id != corp_id:
        raise ValueError(
            f"corp_id mismatch: receive_id={receive_id}, expected={corp_id}"
        )

    return msg


def parse_xml_text(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text.encode("utf-8"))


def find_xml(root: ET.Element, name: str, default: str = "") -> str:
    node = root.find(name)
    if node is None or node.text is None:
        return default
    return node.text


# =============================
# GPT-5.5 中转 API
# =============================

def call_mid_api(user_text: str) -> str:
    mid_api_url = get_env("MID_API_URL")
    mid_api_key = get_env("MID_API_KEY")
    model_name = get_env("MODEL_NAME", "gpt-5.5")
    reasoning_effort = get_env("REASONING_EFFORT", "xhigh")

    if not mid_api_url:
        return "错误：Render 环境变量 MID_API_URL 没有配置。"

    if not mid_api_key:
        return "错误：Render 环境变量 MID_API_KEY 没有配置。"

    chat_url = build_chat_url(mid_api_url)

    headers = {
        "Authorization": f"Bearer {mid_api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个认真、可靠、会充分思考后再回答的中文助手。"
                    "用户通常问的都是实际项目、排错、规划、代码、工具接入问题。"
                    "回答要优先给出稳妥、可执行、少走弯路的方案。"
                    "不要输出你的隐藏思考过程，只输出最终答案。"
                ),
            },
            {
                "role": "user",
                "content": user_text,
            },
        ],
        "temperature": 0.4,
        "reasoning_effort": reasoning_effort,
    }

    try:
        response = requests.post(
            chat_url,
            headers=headers,
            json=payload,
            timeout=180,
        )

        if response.status_code != 200:
            return (
                f"中转 API 请求失败：HTTP {response.status_code}\n"
                f"{response.text[:1000]}"
            )

        data = response.json()

        if "choices" in data and data["choices"]:
            message = data["choices"][0].get("message", {})
            content = message.get("content")
            if content:
                return content.strip()

        if "reply" in data:
            return str(data["reply"]).strip()

        if "text" in data:
            return str(data["text"]).strip()

        return f"中转 API 已返回，但格式未识别：{str(data)[:1000]}"

    except Exception as e:
        return f"调用中转 API 出错：{e}"


# =============================
# 企业微信主动发消息
# =============================

def get_wechat_access_token() -> str:
    corp_id = get_env("CORP_ID")
    secret = get_env("SECRET")

    if not corp_id:
        raise ValueError("CORP_ID is not configured")

    if not secret:
        raise ValueError("SECRET is not configured")

    current = now_ts()

    if TOKEN_CACHE["access_token"] and current < TOKEN_CACHE["expire_at"]:
        return TOKEN_CACHE["access_token"]

    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    params = {
        "corpid": corp_id,
        "corpsecret": secret,
    }

    resp = requests.get(url, params=params, timeout=20)
    data = resp.json()

    if data.get("errcode") != 0:
        raise RuntimeError(f"获取 access_token 失败：{data}")

    access_token = data["access_token"]
    expires_in = int(data.get("expires_in", 7200))

    TOKEN_CACHE["access_token"] = access_token
    TOKEN_CACHE["expire_at"] = current + expires_in - 300

    return access_token


def send_wechat_text(to_user: str, content: str):
    agent_id = get_env("AGENT_ID")

    if not agent_id:
        raise ValueError("AGENT_ID is not configured")

    access_token = get_wechat_access_token()
    url = "https://qyapi.weixin.qq.com/cgi-bin/message/send"
    params = {
        "access_token": access_token,
    }

    for chunk in split_text(content, limit=1800):
        payload = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": int(agent_id),
            "text": {
                "content": chunk,
            },
            "safe": 0,
        }

        resp = requests.post(url, params=params, json=payload, timeout=20)
        data = resp.json()

        if data.get("errcode") != 0:
            print(f"[wechat send error] to_user={to_user}, data={data}")


def process_user_message_async(from_user: str, user_text: str):
    try:
        send_notice = get_env("SEND_THINKING_NOTICE", "true").lower() in (
            "1", "true", "yes", "y"
        )

        if send_notice:
            send_wechat_text(from_user, "收到，我正在认真思考，稍等一下。")

        reply = call_mid_api(user_text)
        send_wechat_text(from_user, reply)

    except Exception as e:
        print(f"[async process error] {e}")


# =============================
# 页面和测试接口
# =============================

@app.route("/", methods=["GET"])
def index():
    return "Hello, GPT bot is running on Render!"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "AGENT_ID": env_exists("AGENT_ID"),
        "CORP_ID": env_exists("CORP_ID"),
        "SECRET": env_exists("SECRET"),
        "MID_API_URL": env_exists("MID_API_URL"),
        "MID_API_KEY": env_exists("MID_API_KEY"),
        "WECHAT_TOKEN": env_exists("WECHAT_TOKEN"),
        "WECHAT_AES_KEY": env_exists("WECHAT_AES_KEY"),
        "MODEL_NAME": get_env("MODEL_NAME", "gpt-5.5"),
        "REASONING_EFFORT": get_env("REASONING_EFFORT", "xhigh"),
        "SEND_THINKING_NOTICE": get_env("SEND_THINKING_NOTICE", "true"),
    })


@app.route("/test", methods=["POST"])
def test_message():
    data = request.get_json(silent=True) or {}

    user_text = (
        data.get("text")
        or data.get("message")
        or data.get("Content")
        or ""
    ).strip()

    if not user_text:
        return jsonify({
            "error": "请传入 text，例如：{\"text\":\"你好\"}"
        }), 400

    reply = call_mid_api(user_text)

    return jsonify({
        "reply": reply
    })


# =============================
# 企业微信正式回调
# =============================

@app.route("/wechat", methods=["GET", "POST"])
def wechat_callback():
    token = get_env("WECHAT_TOKEN")

    if not token:
        return "WECHAT_TOKEN is not configured", 500

    msg_signature = request.args.get("msg_signature", "")
    timestamp = request.args.get("timestamp", "")
    nonce = request.args.get("nonce", "")

    if request.method == "GET":
        echostr = request.args.get("echostr", "")

        if not msg_signature or not timestamp or not nonce or not echostr:
            return "missing query params", 400

        expected_signature = sha1_signature(token, timestamp, nonce, echostr)

        if expected_signature != msg_signature:
            return "invalid signature", 403

        try:
            echo_plain = decrypt_wechat_message(echostr)
            return echo_plain
        except Exception as e:
            print(f"[wechat verify error] {e}")
            return f"decrypt echostr failed: {e}", 500

    raw_xml = request.data.decode("utf-8", errors="ignore")

    if not raw_xml:
        return "empty body", 400

    try:
        root = parse_xml_text(raw_xml)
        encrypted = find_xml(root, "Encrypt")

        if not encrypted:
            return "missing Encrypt", 400

        expected_signature = sha1_signature(token, timestamp, nonce, encrypted)

        if expected_signature != msg_signature:
            return "invalid signature", 403

        decrypted_xml = decrypt_wechat_message(encrypted)
        msg_root = parse_xml_text(decrypted_xml)

        msg_type = find_xml(msg_root, "MsgType")
        from_user = find_xml(msg_root, "FromUserName")
        content = find_xml(msg_root, "Content")
        msg_id = find_xml(msg_root, "MsgId")

        print(
            f"[wechat message] from={from_user}, "
            f"type={msg_type}, msg_id={msg_id}, content={content[:80]}"
        )

        if msg_id and is_duplicate_msg(msg_id):
            print(f"[wechat duplicate] msg_id={msg_id}")
            return "success"

        if msg_type == "text" and from_user and content:
            thread = threading.Thread(
                target=process_user_message_async,
                args=(from_user, content),
                daemon=True,
            )
            thread.start()

        elif from_user:
            send_wechat_text(
                from_user,
                "我目前先支持文字消息，你可以直接发送文字问题给我。"
            )

        return "success"

    except Exception as e:
        print(f"[wechat callback error] {e}")
        return "success"


# =============================
# 启动
# =============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)