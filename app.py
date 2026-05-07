from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

# -----------------------------
# 根路由：测试 Render 是否成功
# -----------------------------
@app.route("/")
def index():
    return "Hello, GPT bot is running on Render!"

# -----------------------------
# 调用中转站 API 的函数
# -----------------------------
def call_transit_api(message):
    # 中转 API URL，从环境变量读取
    transit_url = os.getenv("TRANSIT_API_URL")
    api_key = os.getenv("TRANSIT_API_KEY")

    if not transit_url or not api_key:
        return "Transit API not configured"

    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"message": message}

    try:
        response = requests.post(transit_url, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()  # 返回 JSON
    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# 企业微信消息接收
# -----------------------------
@app.route("/wechat", methods=["POST"])
def wechat():
    data = request.json
    if not data or "Content" not in data:
        return jsonify({"error": "Invalid request"}), 400

    user_msg = data["Content"]
    # 调用中转 API
    gpt_response = call_transit_api(user_msg)

    # 返回给企业微信
    return jsonify({
        "ToUserName": data.get("FromUserName"),
        "FromUserName": data.get("ToUserName"),
        "MsgType": "text",
        "Content": str(gpt_response)
    })

# -----------------------------
# 启动
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)