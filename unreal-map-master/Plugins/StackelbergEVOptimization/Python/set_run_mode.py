from __future__ import annotations

import argparse
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[1] / "Config" / "DefaultStackelbergEVOptimization.ini"


def replace_setting(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    replacement = f"{key}={value}"
    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Select baseline or optimized behavior for the next Unreal Play session.")
    parser.add_argument("mode", choices=("Baseline", "Optimized"))
    parser.add_argument("--plan", help="Plan path relative to Saved, or an absolute path")
    args = parser.parse_args()

    text = CONFIG_PATH.read_text(encoding="utf-8")
    text = replace_setting(text, "RunMode", args.mode)
    if args.plan:
        text = replace_setting(text, "PlanFile", args.plan)
    CONFIG_PATH.write_text(text, encoding="utf-8")
    print(f"RunMode={args.mode}")
    if args.plan:
        print(f"PlanFile={args.plan}")
    print("Restart the Unreal Editor before Play so the plugin reloads this configuration.")


if __name__ == "__main__":
    main()
