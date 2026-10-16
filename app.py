
import os
import re
import html
import requests
import streamlit as st

from html.parser import HTMLParser
from urllib.parse import urlencode
from dotenv import load_dotenv

# =====================================
# 初期設定
# =====================================

load_dotenv()

DIFY_API_KEY = os.getenv("DIFY_API_KEY", "").strip()
DIFY_API_URL = os.getenv(
    "DIFY_API_URL",
    "https://api.dify.ai/v1"
).rstrip("/")

st.set_page_config(
    page_title="チャットbot",
    page_icon="💬",
    layout="centered"
)


# =====================================
# Dify API
# =====================================

def send_dify_message(query, mode, conversation_id=""):

    if not DIFY_API_KEY:
        raise ValueError(
            "DIFY_API_KEYが設定されていません。"
            ".envを確認してください。"
        )

    url = f"{DIFY_API_URL}/chat-messages"

    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "inputs": {"mode": mode},
        "query": query,
        "response_mode": "blocking",
        "conversation_id": conversation_id,
        "user": "streamlit-user"
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=120
        )
    except requests.RequestException as e:
        raise RuntimeError(
            f"Difyへの接続に失敗しました: {e}"
        ) from e

    if not response.ok:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text

        raise RuntimeError(
            f"Dify APIエラー: {response.status_code}\n"
            f"詳細: {detail}"
        )

    return response.json()


def ask_dify(mode, content):

    first_response = send_dify_message(
        query=mode,
        mode=mode
    )

    conversation_id = first_response.get("conversation_id")

    if not conversation_id:
        raise RuntimeError(
            "Difyからconversation_idを取得できませんでした。"
        )

    second_response = send_dify_message(
        query=content,
        mode=mode,
        conversation_id=conversation_id
    )

    answer = second_response.get("answer", "")

    if not answer:
        raise RuntimeError(
            "Difyから回答を取得できませんでした。"
        )

    return answer


# =====================================
# 回答の表示
# =====================================

def display_answer(answer):

    answer = answer.strip()

    if "&lt;div" in answer or "&lt;p" in answer:
        answer = html.unescape(answer)

    is_html = bool(
        re.search(
            r"<(?:div|p|table|section|article|ul|ol)\b",
            answer,
            flags=re.IGNORECASE
        )
    )

    if is_html:
        st.html(answer)
    else:
        st.markdown(answer)


# =====================================
# メール本文の抽出
# =====================================

class HTMLTextExtractor(HTMLParser):

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in ("div", "p", "section", "article"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def get_text(self):
        return "".join(self.parts)


def to_plain_text(answer):

    text = html.unescape(answer)

    if re.search(r"<[a-zA-Z][^>]*>", text):
        parser = HTMLTextExtractor()
        parser.feed(text)
        text = parser.get_text()

    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\\([\\*#._-])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def extract_email(answer):

    text = to_plain_text(answer)

    match = re.search(
        r"■\s*(?:回答|作成されたメール)\s*\n",
        text
    )

    if match:
        text = text[match.end():].strip()

    text = re.split(
        r"\n\s*(?:---\s*\n)?"
        r"続けて利用する場合は",
        text,
        maxsplit=1
    )[0].strip()

    subject_match = re.search(
        r"^(?:件名|Subject)\s*[：:]\s*(.+)$",
        text,
        flags=re.MULTILINE
    )

    if subject_match:
        subject = subject_match.group(1).strip()
        body = (
            text[:subject_match.start()]
            + text[subject_match.end():]
        ).strip()
    else:
        subject = "お問い合わせへのご返信"
        body = text

    return subject, body


# =====================================
# Gmail / Outlook
# =====================================

def gmail_compose_url(subject, body):

    params = urlencode({
        "view": "cm",
        "fs": "1",
        "su": subject,
        "body": body
    })

    return "https://mail.google.com/mail/?" + params


def outlook_compose_url(subject, body):

    params = urlencode({
        "subject": subject,
        "body": body
    })

    return (
        "https://outlook.office.com/mail/"
        "deeplink/compose?" + params
    )


def email_buttons(answer):

    subject, body = extract_email(answer)

    st.divider()
    st.subheader("📨 メールで利用する")

    st.caption(
        "メール作成画面を開きます。"
        "宛先と内容を確認してから送信してください。"
    )

    gmail_url = gmail_compose_url(subject, body)
    outlook_url = outlook_compose_url(subject, body)

    # Outlookで長すぎるURLを送らない
    outlook_too_long = len(outlook_url.encode("utf-8")) > 1500

    if outlook_too_long:
        outlook_url = outlook_compose_url(subject, "")

    col1, col2 = st.columns(2)

    with col1:
        st.link_button(
            "📧 Gmailで開く",
            gmail_url,
            use_container_width=True
        )

    with col2:
        st.link_button(
            "📨 Outlookで開く",
            outlook_url,
            use_container_width=True
        )

    if outlook_too_long:
        st.info(
            "メール本文が長いため、Outlookでは件名のみ"
            "自動入力します。以下の本文をコピーして"
            "Outlookに貼り付けてください。"
        )

        st.code(body, language=None)


# =====================================
# セッション管理
# =====================================

if "results" not in st.session_state:
    st.session_state.results = {}


# =====================================
# メイン画面
# =====================================

st.title("チャットbot")

st.write(
    "メール作成・メール添削・質問回答を"
    "AIがサポートします。"
)

mode = st.selectbox(
    "利用するモードを選択してください",
    [
        "メール作成モード",
        "メール添削モード",
        "質問回答モード"
    ]
)

st.divider()


# =====================================
# メール作成モード
# =====================================

if mode == "メール作成モード":

    st.header("✉️ メール作成")

    st.write(
        "お問い合わせ内容を入力すると、"
        "AIが返信メールを作成します。"
    )

    with st.form("create_form"):

        inquiry = st.text_area(
            "お問い合わせ内容（必須）",
            placeholder="例：受講開始日を変更できますか？",
            height=140
        )

        history = st.text_area(
            "過去のやり取り（任意）",
            placeholder="過去のメールのやり取りがあれば入力",
            height=120
        )

        submitted = st.form_submit_button(
            "メールを作成",
            use_container_width=True
        )

    if submitted:

        if not inquiry.strip():
            st.warning("お問い合わせ内容を入力してください。")

        else:
            content = (
                f"お問い合わせ内容:\n{inquiry}\n\n"
                f"過去のやり取り:\n"
                f"{history.strip() or 'なし'}"
            )

            with st.spinner("AIがメールを作成しています..."):
                try:
                    answer = ask_dify(mode, content)
                    st.session_state.results[mode] = answer
                except Exception as e:
                    st.error(str(e))


# =====================================
# メール添削モード
# =====================================

elif mode == "メール添削モード":

    st.header("📝 メール添削")

    st.write(
        "メールの下書きを入力すると、"
        "AIが文章を添削します。"
    )

    with st.form("edit_form"):

        email = st.text_area(
            "添削したいメール（必須）",
            placeholder=(
                "例：受講開始日を変更したいです。"
                "よろしくお願いします。"
            ),
            height=160
        )

        direction = st.text_area(
            "添削方針（任意）",
            placeholder="例：より丁寧な文章にしてください",
            height=100
        )

        submitted = st.form_submit_button(
            "メールを添削",
            use_container_width=True
        )

    if submitted:

        if not email.strip():
            st.warning("添削したいメールを入力してください。")

        else:
            content = (
                f"添削対象メール:\n{email}\n\n"
                f"添削方針:\n"
                f"{direction.strip() or '指定なし'}"
            )

            with st.spinner("AIがメールを添削しています..."):
                try:
                    answer = ask_dify(mode, content)
                    st.session_state.results[mode] = answer
                except Exception as e:
                    st.error(str(e))


# =====================================
# 質問回答モード
# =====================================

else:

    st.header("💬 質問回答")

    st.write(
        "質問を入力すると、"
        "FAQを参考にAIが回答します。"
    )

    with st.form("question_form"):

        question = st.text_area(
            "質問内容（必須）",
            placeholder="例：受講開始日の変更は可能ですか？",
            height=160
        )

        submitted = st.form_submit_button(
            "質問する",
            use_container_width=True
        )

    if submitted:

        if not question.strip():
            st.warning("質問内容を入力してください。")

        else:
            with st.spinner("AIが回答を作成しています..."):
                try:
                    answer = ask_dify(mode, question)
                    st.session_state.results[mode] = answer
                except Exception as e:
                    st.error(str(e))


# =====================================
# 回答表示
# =====================================

if mode in st.session_state.results:

    st.divider()

    if mode == "メール作成モード":
        st.subheader("📄 作成されたメール")

    elif mode == "メール添削モード":
        st.subheader("📄 添削結果")

    else:
        st.subheader("📄 回答")

    answer = st.session_state.results[mode]

    display_answer(answer)

    if mode in (
        "メール作成モード",
        "メール添削モード"
    ):
        email_buttons(answer)

    if st.button(
        "このモードの結果をクリア",
        use_container_width=True
    ):
        del st.session_state.results[mode]
        st.rerun()


# =====================================
# フッター
# =====================================

st.divider()

st.caption(
    "※ AIの回答は参考情報です。"
    "重要な内容は担当者にご確認ください。"
)
