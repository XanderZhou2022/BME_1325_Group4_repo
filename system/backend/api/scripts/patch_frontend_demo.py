from pathlib import Path

API_DEMO = Path(__file__).resolve().parents[1] / "app" / "demo" / "service.py"
BASE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "showcase"


def patch_demo_service() -> None:
    t = API_DEMO.read_text(encoding="utf-8")
    old = (
        '    progress_emit(\n        {\n            "type": "phase",\n'
        '            "message": f"处理 {len(active_clinical)} 位患者的 Agent 待办（检查/会诊）…",\n        }\n    )\n'
        '    progress_emit(\n        {\n            "type": "phase",\n'
        '            "message": f"阶段 2/3：并行履约 {len(active_clinical)} 位患者的 Agent 待办（检查/会诊）…",\n        }\n    )'
    )
    new = (
        '    progress_emit(\n        {\n            "type": "phase",\n'
        '            "message": f"阶段 2/4：并行履约 {len(active_clinical)} 位患者的 Agent 待办（检查/会诊）…",\n        }\n    )'
    )
    if old in t:
        t = t.replace(old, new)
    t = t.replace("阶段 3/3：", "阶段 3/4：")
    API_DEMO.write_text(t, encoding="utf-8")
    print("demo service phases ok")


def patch_progress() -> None:
    p = BASE / "autoDemoProgress.ts"
    t = p.read_text(encoding="utf-8")
    if "ward_batch_start" in t:
        return
    t = t.replace(
        '    case "phase":\n      return `${prefix}${String(ev.message ?? "处理中…")}`;',
        '    case "ward_batch_start":\n      return `${prefix}${String(ev.message ?? "全病房 Agent 批次开始…")}`;\n'
        "    case \"ward_batch_done\": {\n"
        '      const st = ev.status === "error" ? "失败" : "完成";\n'
        '      return `${prefix}ward_coordinator 全病房批次${st}，队列 ${ev.queue_size ?? "—"} 人，${ev.duration_ms ?? "?"}ms`;\n'
        "    }\n"
        '    case "phase":\n      return `${prefix}${String(ev.message ?? "处理中…")}`;',
    )
    t = t.replace(
        '  if (ev.type?.startsWith("agent_") || ev.type === "patient_clinical_start") return "agent";',
        '  if (ev.type === "ward_batch_start" || ev.type === "ward_batch_done") return "agent";\n'
        '  if (ev.type?.startsWith("agent_") || ev.type === "patient_clinical_start") return "agent";',
    )
    p.write_text(t, encoding="utf-8")
    print("progress ok")


def patch_narrative() -> None:
    p = BASE / "autoDemoNarrative.ts"
    t = p.read_text(encoding="utf-8")
    if "并行患者" in t:
        return
    t = t.replace(
        '    lines.push(`Ward batch tick: ${n} sub-event(s). Anchor admission for risk snapshot: ${aid || "N/A"}.`);',
        '    lines.push(`Ward batch tick (出入院 → 并行患者 → 全病房 Agent): ${n} sub-event(s). Anchor: ${aid || "N/A"}.`);',
    )
    t = t.replace(
        "      lines.push(`Mix: ${Object.entries(types)",
        '      if (types["ward_coordinator_batch"]) {\n'
        '        lines.push("Ward coordinator ran once for the whole ICU after all patients were processed.");\n'
        "      }\n"
        '      if (types["admissions_batch_complete"]) {\n'
        '        lines.push("All admissions/discharges for this step completed before patient agents.");\n'
        "      }\n"
        "      lines.push(`Mix: ${Object.entries(types)",
    )
    p.write_text(t, encoding="utf-8")
    print("narrative ok")


def patch_step_events() -> None:
    p = BASE / "autoDemoStepEvents.ts"
    t = p.read_text(encoding="utf-8")
    if "admissions_batch_complete" in t:
        return
    block = """    if (type === "admissions_batch_complete") {
      const created = Number((sub as JsonObj).admissions_created ?? 0);
      const dis = Number((sub as JsonObj).discharges ?? 0);
      return {
        index: index + 1,
        type,
        admission_id: "",
        bed_id: "",
        patient_id: "",
        title: "出入院批次完成",
        details: [`新收治 ${created} 人`, `出院 ${dis} 人`, "随后才启动患者级 Agent"],
        tone: "admin",
      };
    }

    if (type === "ward_coordinator_batch") {
      return {
        index: index + 1,
        type,
        admission_id: String((sub as JsonObj).anchor_admission_id ?? ""),
        bed_id: "",
        patient_id: "",
        title: "全病房 ward_coordinator",
        details: [
          `状态: ${String((sub as JsonObj).status ?? "—")}`,
          `队列: ${String((sub as JsonObj).queue_size ?? "—")} 人`,
          `负荷: ${String((sub as JsonObj).ward_load_indicator ?? "—")}`,
        ],
        tone: "admin",
      };
    }

"""
    t = t.replace('    if (type === "admission_discharge") {', block + '    if (type === "admission_discharge") {', 1)
    p.write_text(t, encoding="utf-8")
    print("step events ok")


if __name__ == "__main__":
    patch_demo_service()
    patch_progress()
    patch_narrative()
    patch_step_events()
