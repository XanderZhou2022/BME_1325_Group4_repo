"""DashScope 流式对话冒烟测试（与 ICU Agent 共用 api调用测试/.env）。"""
from openai import OpenAI

from llm_env import DASHSCOPE_BASE_URL, chat_completions_url, get_api_key, get_model

api_key = get_api_key()
if not api_key:
    raise ValueError("没有读取到 DASHSCOPE_API_KEY，请检查 .env 文件路径和变量名")

client = OpenAI(api_key=api_key, base_url=DASHSCOPE_BASE_URL)

messages = [{"role": "user", "content": "你是谁"}]
completion = client.chat.completions.create(
    model=get_model(),
    messages=messages,
    extra_body={"enable_thinking": True},
    stream=True,
)
is_answering = False
print("\n" + "=" * 20 + "思考过程" + "=" * 20)
for chunk in completion:
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta
    if hasattr(delta, "reasoning_content") and delta.reasoning_content is not None:
        if not is_answering:
            print(delta.reasoning_content, end="", flush=True)
    if hasattr(delta, "content") and delta.content:
        if not is_answering:
            print("\n" + "=" * 20 + "完整回复" + "=" * 20)
            is_answering = True
        print(delta.content, end="", flush=True)

# 非 Agent 路径的 URL 拼接（仅文档/调试）
_ = chat_completions_url()
