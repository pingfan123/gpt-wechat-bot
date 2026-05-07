from flask import Flask, request
import requests, os

app = Flask(__name__)

# ====== 企业微信配置（环境变量） ======
CORP_ID = os.environ.get("CORP_ID")
SECRET = os.environ.get("SECRET")
AGENT_ID = os.environ.get("AGENT_ID")

# ====== 中转 API 配置（环境变量） ======
MID_API_URL = os.environ.get("MID_API_URL")  # 中转站接口
MID_API_KEY = os.environ.get("MID_API_KEY")  # 中转 Key

# ---------- 企业微信 access_token ----------
def get_access_token():
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={CORP_ID}&corpsecret={SECRET}"
    r = requests.get(url)
    return r.json().get("access_token")

# ---------- Webhook 接收消息 ----------
@app.route("/wechat_callback", methods=['POST'])
def wechat_callback():
    data = request.json
    user_msg = data.get("Content", "")
    from_user = data.get("FromUserName", "")

    # 调用中转 API
    try:
        payload = {"prompt": user_msg, "key": MID_API_KEY}
        r = requests.post(MID_API_URL, json=payload, timeout=10)
        r.raise_for_status()
        reply_msg = r.json().get("text", "抱歉，接口没有返回内容")
    except Exception as e:
        reply_msg = f"调用中转 API 出错：{e}"

    # 回复企业微信
    try:
        token = get_access_token()
        send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        payload = {
            "touser": from_user,
            "msgtype": "text",
            "agentid": int(AGENT_ID),
            "text": {"content": reply_msg},
            "safe": 0
        }
        requests.post(send_url, json=payload, timeout=5)
    except Exception as e:
        print(f"发送给企业微信失败：{e}")

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)