import json

wf = json.loads(open(r"C:\Users\zhangbo\.openclaw-autoclaw\agents\agent-gotxja\workspace\.openclaw-attachments\20260624-095550-273e8aaf-2ad-wear(qwen-image-edit).json", encoding="utf-8").read())

for k, v in sorted([(k,v) for k,v in wf.items() if k.isdigit()], key=lambda x: int(x[0])):
    title = v.get("_meta", {}).get("title", "") if isinstance(v, dict) else ""
    ct = v.get("class_type", "?")
    mark = " <===" if "渲染图" in title or "提示词" in title or ct == "SaveImage" else ""
    print(f"  {k:>4s}: {ct:<38s} | {title}{mark}")

print()
for nid in ["4", "25", "51", "21"]:
    n = wf.get(nid, {})
    print(f"node {nid}: class_type={n.get('class_type','MISSING')}  title={n.get('_meta',{}).get('title','')}")

# check if there's a SaveImage output node for AIDiffMask
for nid, n in wf.items():
    if n.get("class_type") == "AIDiffMaskNode":
        print(f"AIDiffMaskNode at {nid}")
    if n.get("class_type") == "SaveImage":
        # what node feeds into this SaveImage?
        inputs = n.get("inputs", {})
        for kk, vv in inputs.items():
            if isinstance(vv, list) and len(vv) == 2:
                src_nid = str(vv[0])
                src = wf.get(src_nid, {})
                print(f"  SaveImage({nid}).{kk} -> {src.get('class_type','?')}({src_nid}) {src.get('_meta',{}).get('title','')}")
