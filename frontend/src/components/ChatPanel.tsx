import { useEffect, useMemo, useRef, useState } from "react";

import type { Message } from "../types";

type Props = {
  messages: Message[];
  disabled: boolean;
  placeholder?: string;
  helperText?: string | null;
  onSend: (content: string) => Promise<void> | void;
};

function roleLabel(role: Message["role"]) {
  if (role === "system") return "系统";
  if (role === "patient") return "患者";
  if (role === "nurse") return "护士";
  if (role === "doctor") return "医生";
  if (role === "pharmacist") return "药师";
  return role;
}

export function ChatPanel({
  messages,
  disabled,
  placeholder,
  helperText,
  onSend,
}: Props) {
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement | null>(null);

  const canSend = useMemo(() => !disabled && text.trim().length > 0, [disabled, text]);

  useEffect(() => {
    // Auto-scroll to bottom when new messages arrive.
    listRef.current?.scrollTo({ top: 999999, behavior: "smooth" });
  }, [messages.length]);

  async function submit() {
    const content = text.trim();
    if (!content || disabled) return;
    setText("");
    await onSend(content);
  }

  return (
    <div className="chatPanel">
      <div className="chatHeader">
        <div>对话</div>
        {helperText ? <div className="chatHelper">{helperText}</div> : null}
      </div>

      <div className="chatList" ref={listRef}>
        {messages.map((m) => (
          <div
            key={m.id}
            className={m.role === "system" ? "chatMsg system" : "chatMsg"}
          >
            <div className="chatRole">{roleLabel(m.role)}</div>
            <div className="chatContent">{m.content}</div>
          </div>
        ))}
      </div>

      <div className="chatComposer">
        <input
          className="chatInput"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={disabled ? "当前不可发送" : placeholder ?? "输入患者消息..."}
          disabled={disabled}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
        />
        <button className="chatSendBtn" disabled={!canSend} onClick={submit}>
          发送
        </button>
      </div>
    </div>
  );
}

