import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)


# =============================
# 基础工具
# =============================

def get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_exists(name: str) -> bool:
    return bool(get_env(name))


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


# =============================
# 页面测试
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
        "MODEL_NAME": get_env("MODEL_NAME", "gpt-5.5"),
        "REASONING_EFFORT": get_env("REASONING_EFFORT", "xhigh"),
    })


# =============================
# 调用中转站 GPT API
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
            timeout=120,
        )

        if response.status_code != 200:
            return (
                f"中转 API 请求失败：HTTP {response.status_code}\n"
                f"{response.text[:800]}"
            )

        data = response.json()

        # OpenAI Chat Completions 格式
        if "choices" in data and data["choices"]:
            message = data["choices"][0].get("message", {})
            content = message.get("content")
            if content:
                return content.strip()

        # 兼容部分中转站格式
        if "reply" in data:
            return str(data["reply"]).strip()

        if "text" in data:
            return str(data["text"]).strip()

        return f"中转 API 已返回，但格式未识别：{str(data)[:800]}"

    except Exception as e:
        return f"调用中转 API 出错：{e}"


# =============================
# 本地 / Render 测试接口
# =============================

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
# 企业微信临时 JSON 测试接口
# 注意：这还不是企业微信官方加密回调完整版
# =============================

@app.route("/wechat", methods=["GET", "POST"])
def wechat():
    if request.method == "GET":
        return (
            "wechat endpoint is alive. "
            "正式企业微信 API 接收还需要 Token / EncodingAESKey / msg_signature 解密校验。"
        )

    data = request.get_json(silent=True) or {}

    user_text = (
        data.get("Content")
        or data.get("text")
        or data.get("message")
        or ""
    ).strip()

    if not user_text:
        return jsonify({
            "error": "Invalid request. Need Content/text/message."
        }), 400

    reply = call_mid_api(user_text)

    return jsonify({
        "Content": reply
    })


# =============================
# 启动
# =============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)