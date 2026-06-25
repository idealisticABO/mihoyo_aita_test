import json

path = r"C:\Users\zhangbo\.openclaw-autoclaw\agents\agent-gotxja\workspace\.openclaw-attachments\20260624-095550-273e8aaf-2ad-wear(qwen-image-edit).json"
d = json.loads(open(path, encoding="utf-8").read())

print("Format:", "workspace" if "nodes" in d else "prompt")
nodes = d.get("nodes", [])
print("\nAll nodes:")
for n in nodes:
    nid = n.get("id", "?")
    ntype = n.get("type", "?")
    title = n.get("title", "")
    mode = n.get("mode", 0)
    mark = ""
    if "渲染图" in title or "提示词" in title:
        mark = " <==="
    print(f"  {nid:>4d}: {ntype:<40s} mode={mode} | {title}{mark}")

# Find key nodes
for n in nodes:
    if "渲染图" in n.get("title", ""):
        print(f"\nINPUT IMAGE: id={n['id']} type={n.get('type')}")
    if "提示词" in n.get("title", ""):
        print(f"\nPROMPT NODE: id={n['id']} type={n.get('type')}")

# Find SaveImage output nodes and what feeds into them
print("\nSaveImage outputs + upstream:")
for n in nodes:
    if n.get("type") == "SaveImage":
        nid = n["id"]
        # Find links feeding into this node
        inputs = n.get("inputs", [])
        for inp in inputs:
            print(f"  SaveImage({nid}) input: link={inp.get('link')}")

print("\nLinks pointing to SaveImages:")
links = d.get("links", [])
saveimg_ids = {str(n["id"]) for n in nodes if n.get("type") == "SaveImage"}
for link in links:
    target_id = str(link[3]) if len(link) > 3 else "?"
    if target_id in saveimg_ids:
        src_id = link[1]
        src_node = next((n for n in nodes if n["id"] == src_id), None)
        src_type = src_node.get("type", "?") if src_node else "?"
        dst_node = next((n for n in nodes if n["id"] == int(target_id)), None)
        dst_title = dst_node.get("title", "") if dst_node else ""
        print(f"  node {src_type}({src_id}) -> SaveImage({target_id}) title={dst_title}")
