"""
Accuracy analyzer for captured necrosis outputs.

Reads every necrosis_audit/*.json (demo = findings at top level; live = report.findings)
and checks each finding against accuracy invariants, writing _ANALYSIS.md.
"""
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = Path(__file__).parent
TLDS = {"com", "org", "net", "io", "gov", "edu", "co", "uk", "dev", "app"}
TEST_RE = re.compile(r"(_test\.(go|py|rb|js)|_spec\.rb|\.(spec|test)\.(js|ts|py|rb)|/spec/|/test/|/tests/)", re.I)


def load(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    if "report" in d and d["report"]:          # live scan file
        return d["report"].get("findings", []), d["report"].get("summary", {}), "live"
    if "findings" in d:                          # demo file
        return d.get("findings", []), d.get("summary", {}), "demo"
    return [], {}, "error/" + str(d.get("_error", "?"))[:60]


def analyze_file(path):
    findings, summary, kind = load(path)
    issues = []
    stats = {"file_sym": 0, "tld_sym": 0, "excise_violation": 0, "reliable_field": 0,
             "spec_caller": 0, "excise_old_ok": 0, "excise_young": 0, "dup": 0}
    seen = set()
    for f in findings:
        name = f.get("name", "")
        safety = f.get("deletion_safety", {})
        rec = safety.get("recommendation")
        callers = safety.get("callers_found", -1)
        caller_files = safety.get("caller_files", [])
        age = f.get("age_days", 0)
        fp = f.get("file_path", "")

        if name.startswith("file:"):
            stats["file_sym"] += 1
            issues.append(f"  [file: symbol]  {name}  ({fp})")
        if name.lower() in TLDS:
            stats["tld_sym"] += 1
            issues.append(f"  [TLD symbol]    {name!r}  ({fp})")
        if rec == "excise_now" and callers not in (0,):
            stats["excise_violation"] += 1
            issues.append(f"  [SAFETY VIOLATION] excise_now with {callers} callers: {name}")
        if "caller_count_reliable" in safety:
            stats["reliable_field"] += 1
        spec_callers = [c for c in caller_files if TEST_RE.search(c)]
        if spec_callers:
            stats["spec_caller"] += 1
            issues.append(f"  [spec/test counted as caller] {name}: {spec_callers}")
        if rec == "excise_now":
            if age >= 180:
                stats["excise_old_ok"] += 1
            else:
                stats["excise_young"] += 1
                issues.append(f"  [excise but young: {age}d] {name}")
        key = (name, fp)
        if key in seen:
            stats["dup"] += 1
            issues.append(f"  [duplicate] {name} ({fp})")
        seen.add(key)

    return kind, len(findings), summary, stats, issues


def main():
    files = sorted(p for p in OUT.glob("*.json") if not p.name.startswith("_"))
    lines = ["# Necrosis audit — accuracy analysis", ""]
    grand = {"file_sym": 0, "tld_sym": 0, "excise_violation": 0, "spec_caller": 0, "dup": 0}
    for path in files:
        kind, n, summary, stats, issues = analyze_file(path)
        lines.append(f"## {path.stem}  ({kind})")
        lines.append(f"- findings: {n} | summary: excise={summary.get('excise_now','?')} "
                     f"biopsy={summary.get('needs_biopsy','?')} intact={summary.get('leave_intact','?')}")
        lines.append(f"- file: symbols={stats['file_sym']} | TLD symbols={stats['tld_sym']} | "
                     f"excise-safety-violations={stats['excise_violation']} | "
                     f"spec-as-caller={stats['spec_caller']} | duplicates={stats['dup']}")
        lines.append(f"- caller_count_reliable field present on {stats['reliable_field']}/{n} findings "
                     f"(0 = pre-fix cached data; >0 = fixed pipeline)")
        lines.append(f"- excise_now: {stats['excise_old_ok']} aged>=180d (ok), {stats['excise_young']} young (suspicious)")
        if issues:
            lines.append("- ISSUES:")
            lines.extend(issues)
        else:
            lines.append("- no issues flagged ✓")
        lines.append("")
        for k in grand:
            grand[k] += stats[k]
    lines.append("## TOTALS across all captured files")
    lines.append(f"- file: symbols: {grand['file_sym']}")
    lines.append(f"- TLD symbols: {grand['tld_sym']}")
    lines.append(f"- excise_now safety violations: {grand['excise_violation']}")
    lines.append(f"- spec/test counted as caller: {grand['spec_caller']}")
    lines.append(f"- duplicates: {grand['dup']}")
    (OUT / "_ANALYSIS.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
