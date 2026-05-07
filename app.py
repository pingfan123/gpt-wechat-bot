from flask import Flask, request
import requests, json
import openai

app = Flask(__name__)

# ====== 配置区 ======
CORP_ID = "你的企业ID(CorpID)"
SECRET = "你的应用Secret"
AGENT_ID = "你的应用AgentId"
GPT_API_KEY = "你的GPT或Codex API Key"
# ==================

def get_access_token():
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={CORP_ID}&corpsecret={SECRET}"
    r = requests.get(url)
    return r.json()["access_token"]

@app.route("/wechat_callback", methods=['POST'])
def wechat_callback():
    data = request.json
    user_msg = data.get("Content", "")
    from_user = data.get("FromUserName", "")

    # 调用 GPT API
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": user_msg}],
        api_key=GPT_API_KEY
    )
    reply_msg = response['choices'][0]['message']['content']

    # 发送消息回企业微信
    token = get_access_token()
    send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": from_user,
        "msgtype": "text",
        "agentid": int(AGENT_ID),
        "text": {"content": reply_msg},
        "safe": 0
    }
    requests.post(send_url, json=payload)
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)