import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)


def env_ok(name: str) -> bool:
    return bool(os.getenv(name))


@app.route("/", methods=["GET"])
def index():
    return "Hello, GPT bot is running on Render!"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "AGENT_ID": env_ok("AGENT_ID"),
        "CORP_ID": env_ok("CORP_ID"),
        "SECRET": env_ok("SECRET"),
        "MID_API_URL": env_ok("MID_API_URL"),
        "MID_API_KEY": env_ok("MID_API_KEY"),
    })


def build_chat_url(raw_url: str) -> str:
    """
    兼容两种填法：
    1. MID_API_URL=https://chunfeng.mentalout.top/
    2. MID_API_URL=https://chunfeng.mentalout.top/v1/chat/completions
    """
    url = raw_url.strip().rstrip("/")

    if url.endswith("/v1/chat/completions"):
        return url

    if url.endswith("/v1"):
        return url + "/chat/completions"

    return url + "/v1/chat/completions"


def call_mid_api(user_text: str) -> str:
    mid_api_url = os.getenv("MID_API_URL")
    mid_api_key = os.getenv("MID_API_KEY")
    model_name = os.getenv("MODEL_NAME", "gpt-4o-mini")

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
                "content": "你是一个简洁、可靠的中文助手。"
            },
            {
                "role": "user",
                "content": user_text
            }
        ],
        "temperature": 0.7,
    }

    try:
        response = requests.post(
            chat_url,
            headers=headers,
            json=payload,
            timeout=60,
        )

        if response.status_code != 200:
            return f"中转 API 请求失败：HTTP {response.status_code}\n{response.text[:500]}"

        data = response.json()

        if "choices" in data and data["choices"]:
            message = data["choices"][0].get("message", {})
            content = message.get("content")
            if content:
                return content

        if "reply" in data:
            return str(data["reply"])

        if "text" in data:
            return str(data["text"])

        return f"中转 API 已返回，但格式未识别：{str(data)[:500]}"

    except Exception as e:
        return f"调用中转 API 出错：{e}"


@app.route("/test", methods=["POST"])
def test_message():
    data = request.get_json(silent=True) or {}
    user_text = data.get("text") or data.get("message") or data.get("Content")

    if not user_text:
        return jsonify({
            "error": "请传入 text，例如：{\"text\":\"你好\"}"
        }), 400

    reply = call_mid_api(user_text)
    return jsonify({
        "reply": reply
    })


@app.route("/wechat", methods=["POST"])
def wechat_json_test():
    """
    注意：
    这个接口目前只用于 JSON 测试，不是企业微信官方加密回调完整版。
    企业微信正式 API 接收还需要 Token、EncodingAESKey、msg_signature 解密校验。
    """
    data = request.get_json(silent=True) or {}
    user_text = data.get("Content") or data.get("text") or data.get("message")

    if not user_text:
        return jsonify({
            "error": "Invalid request. Need Content/text/message."
        }), 400

    reply = call_mid_api(user_text)
    return jsonify({
        "Content": reply
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)