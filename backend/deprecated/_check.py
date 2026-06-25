import json

path = r"C:\Users\zhangbo\.openclaw-autoclaw\agents\agent-gotxja\workspace\.openclaw-attachments\20260624-111229-5b090cef-942-wear(qwen-image-edit)-0624.json"
wf = json.loads(open(path, encoding="utf-8").read())

for k in sorted(wf.keys(), key=lambda x: int(x) if x.isdigit() else 0):
    v = wf[k]
    if not isinstance(v, dict):
        continue
    title = v.get("_meta", {}).get("title", "")
    ct = v.get("class_type", "?")
    mark = " <===" if "渲染图" in title or "提示词" in title or ct == "SaveImage" else ""
    print(f"  {k:>4s}: {ct:<38s} | {title}{mark}")

# check 4, 25, 21, 51
for nid in ["4", "25", "21", "51"]:
    n = wf.get(nid)
    if n:
        print(f"\nnode {nid}: class_type={n['class_type']} title={n.get('_meta',{}).get('title','')}")
    else:
        print(f"\nnode {nid}: MISSING")
