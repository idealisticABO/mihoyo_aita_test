import json, os

files = [
  r"C:\Users\zhangbo\.openclaw-autoclaw\agents\agent-gotxja\workspace\.openclaw-attachments\20260623-215213-385ce645-cf1-wear(gpt-image-2）.json",
  r"C:\Users\zhangbo\.openclaw-autoclaw\agents\agent-gotxja\workspace\.openclaw-attachments\20260623-215213-ab782366-0b9-wear(nano-banana).json",
  r"C:\Users\zhangbo\.openclaw-autoclaw\agents\agent-gotxja\workspace\.openclaw-attachments\20260623-215213-55949205-8f9-wear(qwen-image-edit).json",
]
for f in files:
    wf = json.loads(open(f, encoding="utf-8").read())
    print("=== " + os.path.basename(f) + " ===")
    for k, v in sorted(wf.items(), key=lambda x: int(x[0])):
        title = v.get("_meta", {}).get("title", "")
        ct = v.get("class_type", "?")
        mark = ""
        if "渲染图输入" in title or "提示词输入" in title or ct == "SaveImage":
            mark = "  <==="
        print(f"  {k:>4s}: {ct:<34s} | {title}{mark}")
    print()
