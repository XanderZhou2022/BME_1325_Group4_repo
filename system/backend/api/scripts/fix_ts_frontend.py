from pathlib import Path

page = Path(__file__).resolve().parents[3] / "frontend" / "src" / "showcase" / "AutoDemoPage.tsx"
prog = Path(__file__).resolve().parents[3] / "frontend" / "src" / "showcase" / "autoDemoProgress.ts"

t = page.read_text(encoding="utf-8")
t = t.replace("const progressEndRef = useRef<HTMLDivElement>(null);", "const progressEndRef = useRef<HTMLLIElement>(null);")
t = t.replace("  type TimelineStepEntry,\n", "")
page.write_text(t, encoding="utf-8")

p = prog.read_text(encoding="utf-8")
p = p.replace(
    "  const t = new Date(ev.ts as string | undefined).toLocaleTimeString",
    "  const t = new Date(ev.ts ? String(ev.ts) : 0).toLocaleTimeString",
)
prog.write_text(p, encoding="utf-8")
print("ok")
