import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

import type { Encounter, Message, Role, Room, Stage } from "./types";
import {
  createEncounter,
  finishEncounter,
  getMessages,
  moveEncounter,
  orderTest,
  resetEncounter,
  sendPatientMessage,
} from "./api";

import { ChatPanel } from "./components/ChatPanel";
import { HospitalPhaser } from "./components/HospitalPhaser";
import { StatusPanel } from "./components/StatusPanel";
import type { HospitalScene } from "./phaser/HospitalScene";

function requiredRoomForStage(stage: Stage): Room | null {
  if (stage === "triage") return "triage_room";
  if (stage === "consultation") return "doctor_room";
  if (stage === "pharmacy") return "pharmacy_room";
  return null;
}

function requiredRoleForStage(stage: Stage): Role | null {
  if (stage === "triage") return "nurse";
  if (stage === "consultation") return "doctor";
  if (stage === "pharmacy") return "pharmacist";
  return null;
}

function rolePlaceholder(role: Role | null) {
  if (!role) return "输入患者消息...";
  if (role === "nurse") return "输入给护士的话（分诊）...";
  if (role === "doctor") return "输入给医生的问题（问诊）...";
  if (role === "pharmacist") return "输入给药师的话（取药）...";
  return "输入患者消息...";
}

function defaultPatientMessageForRole(role: Role): string {
  if (role === "nurse")
    return "我感觉不太舒服，主要是头痛和轻度发热，持续了大概两天。";
  if (role === "doctor") return "我不适主要在头部，程度大概是中等。";
  if (role === "pharmacist") return "请问药品需要怎么服用？";
  return "我想咨询一下。";
}

function computeCanInteract(encounter: Encounter | null) {
  if (!encounter) return false;
  const required = requiredRoomForStage(encounter.stage);
  if (!required) return false;
  return encounter.current_room === required && encounter.status !== "completed";
}

function patientMessageCountInCurrentStage(messages: Message[], encounter: Encounter) {
  const offset = Math.max(0, encounter.stage_message_offset ?? 0);
  return messages.slice(offset).filter((m) => m.role === "patient").length;
}

export default function App() {
  const [encounter, setEncounter] = useState<Encounter | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [canInteract, setCanInteract] = useState(false);
  const [loading, setLoading] = useState(false);
  const sceneRef = useRef<HospitalScene | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await createEncounter();
        if (cancelled) return;
        setEncounter(res);
        setMessages(res.messages);
        setCanInteract(res.can_interact);
      } catch (e) {
        // eslint-disable-next-line no-console
        console.error(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const helperText = useMemo(() => {
    if (!encounter) return "初始化中...";
    if (encounter.status === "completed") return "已完成本次就诊。";
    if (canInteract) return "当前房间正确，可以开始对话/操作。";
    const required = requiredRoomForStage(encounter.stage);
    if (!required) return null;
    const pretty =
      required === "triage_room" ? "分诊室" : required === "doctor_room" ? "医生诊室" : "药房";
    return `请前往${pretty}。`;
  }, [canInteract, encounter]);

  async function syncMessages(encounterId: string) {
    const msgRes = await getMessages(encounterId);
    setMessages(msgRes.messages);
    setCanInteract(msgRes.can_interact);
  }

  async function onRoomClick(room: Room) {
    if (!encounter || loading) return;
    setLoading(true);
    try {
      const res = await moveEncounter(encounter.id, room);
      setEncounter(res.encounter);
      sceneRef.current?.goToRoom(room);
      await syncMessages(res.encounter.id);
    } finally {
      setLoading(false);
    }
  }

  async function onSend(content: string) {
    if (!encounter || loading) return;
    setLoading(true);
    try {
      const res = await sendPatientMessage(encounter.id, content);
      setEncounter(res.encounter);
      setMessages(res.messages);
      setCanInteract(res.can_interact);
    } finally {
      setLoading(false);
    }
  }

  async function onNpcClick(role: Role) {
    if (!encounter || loading) return;
    const requiredRole = requiredRoleForStage(encounter.stage);
    if (!requiredRole || requiredRole !== role) return;
    if (!canInteract) return;
    const patientCount = patientMessageCountInCurrentStage(messages, encounter);
    if (patientCount > 0) return;
    const content = defaultPatientMessageForRole(role);
    await onSend(content);
  }

  async function onTriggerOrderTest() {
    if (!encounter || loading) return;
    setLoading(true);
    try {
      const res = await orderTest(encounter.id);
      if (res.error) return;
      setEncounter(res.encounter);
      setMessages(res.messages);
      setCanInteract(computeCanInteract(res.encounter));
    } finally {
      setLoading(false);
    }
  }

  async function onFinishEncounter() {
    if (!encounter || loading) return;
    setLoading(true);
    try {
      const res = await finishEncounter(encounter.id);
      if (res.error) return;
      setEncounter(res.encounter);
      setMessages(res.messages);
      setCanInteract(false);
    } finally {
      setLoading(false);
    }
  }

  async function onReset() {
    if (!encounter || loading) return;
    setLoading(true);
    try {
      const res = await resetEncounter(encounter.id);
      setEncounter(res);
      setMessages(res.messages);
      setCanInteract(res.can_interact);
      sceneRef.current?.goToRoom("lobby");
    } finally {
      setLoading(false);
    }
  }

  const requiredRole = requiredRoleForStage(encounter?.stage ?? "triage");
  const disabledChat =
    !canInteract || loading || (encounter?.status === "completed");

  const showOrderTest =
    encounter?.stage === "consultation" && encounter.current_room === "doctor_room";
  const showFinish =
    encounter?.stage === "pharmacy" && encounter.current_room === "pharmacy_room";

  return (
    <div className="appRoot">
      <div className="actionBar">
        <button className="actionBtn" onClick={onReset} disabled={!encounter || loading}>
          重新开始
        </button>
        <button
          className="actionBtn secondary"
          onClick={onTriggerOrderTest}
          disabled={!encounter || loading || !showOrderTest}
        >
          触发一次检查
        </button>
        <button
          className="actionBtn danger"
          onClick={onFinishEncounter}
          disabled={!encounter || loading || !showFinish}
        >
          完成取药并结束
        </button>
        {loading ? <span>处理中...</span> : null}
      </div>

      <div className="topRow">
        <div className="mapArea">
          <HospitalPhaser
            currentRoom={encounter?.current_room ?? "lobby"}
            stage={encounter?.stage ?? "triage"}
            onRoomClick={onRoomClick}
            onNpcClick={onNpcClick}
            onSceneReady={(scene) => {
              sceneRef.current = scene;
              if (encounter) scene.goToRoom(encounter.current_room);
            }}
          />
        </div>

        <div className="statusArea">
          {encounter ? (
            <StatusPanel encounter={encounter} />
          ) : (
            <div style={{ padding: 12 }}>加载中...</div>
          )}
        </div>
      </div>

      <div className="chatArea">
        <ChatPanel
          messages={messages}
          disabled={disabledChat}
          helperText={helperText}
          placeholder={rolePlaceholder(requiredRole)}
          onSend={onSend}
        />
      </div>
    </div>
  );
}
