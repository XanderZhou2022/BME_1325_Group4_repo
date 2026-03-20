import type { Encounter } from "../types";

type Props = {
  encounter: Encounter;
};

function prettyRoom(room: Encounter["current_room"]) {
  if (room === "lobby") return "大厅";
  if (room === "triage_room") return "分诊室";
  if (room === "doctor_room") return "医生诊室";
  if (room === "pharmacy_room") return "药房";
  return room;
}

function prettyStage(stage: Encounter["stage"]) {
  if (stage === "triage") return "分诊";
  if (stage === "consultation") return "问诊/咨询";
  if (stage === "pharmacy") return "取药/药房";
  if (stage === "completed") return "完成";
  return stage;
}

export function StatusPanel({ encounter }: Props) {
  const c = encounter.clinical;
  return (
    <div className="statusPanel">
      <div className="panelTitle">病历/状态</div>

      <div className="panelSection">
        <div className="kv">
          <span>患者</span>
          <b>
            {encounter.patient.name}（{encounter.patient.age}岁，{encounter.patient.gender}）
          </b>
        </div>
        <div className="kv">
          <span>chief complaint</span>
          <div className="mono">{encounter.patient.chief_complaint}</div>
        </div>
      </div>

      <div className="panelSection">
        <div className="kv">
          <span>当前阶段</span>
          <b>{prettyStage(encounter.stage)}</b>
        </div>
        <div className="kv">
          <span>当前房间</span>
          <b>{prettyRoom(encounter.current_room)}</b>
        </div>
        <div className="kv">
          <span>分配科室</span>
          <b>{encounter.assigned_department}</b>
        </div>
        <div className="kv">
          <span>encounter 状态</span>
          <b>{encounter.status}</b>
        </div>
      </div>

      <div className="panelSection">
        <div className="panelSubTitle">检查结果</div>
        {c.lab_results.length ? (
          <ul className="list">
            {c.lab_results.map((r, idx) => (
              <li key={`${idx}-${r}`}>{r}</li>
            ))}
          </ul>
        ) : (
          <div className="muted">N/A</div>
        )}
      </div>

      <div className="panelSection">
        <div className="panelSubTitle">初步诊断</div>
        {c.initial_diagnosis ? <div className="mono">{c.initial_diagnosis}</div> : <div className="muted">N/A</div>}
      </div>

      <div className="panelSection">
        <div className="panelSubTitle">处方信息</div>
        {c.prescription ? <pre className="prescription">{c.prescription}</pre> : <div className="muted">N/A</div>}
      </div>
    </div>
  );
}

