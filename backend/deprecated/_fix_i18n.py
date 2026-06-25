import re

path = r"C:\Users\zhangbo\.openclaw-autoclaw\agents\agent-gotxja\workspace\blender-pipeline\backend\app\api\routes\tasks.py"
with open(path, encoding="utf-8") as f:
    content = f.read()

mappings = {
    "task not found": "任务不存在",
    "file not found": "文件不存在",
    "no running job for this task": "没有正在运行的任务可取消",
    "unknown camera": "未知的相机视角",
}

for eng, cn in mappings.items():
    count = 0
    # handle detail="..."
    old = f'detail="{eng}"'
    new = f'detail="{cn}"'
    if old in content:
        content = content.replace(old, new)
        count += 1
    # handle JSON "detail": "..."
    old2 = f'"detail": "{eng}"'
    new2 = f'"detail": "{cn}"'
    if old2 in content:
        content = content.replace(old2, new2)
        count += 1
    if count:
        print(f"replaced {count}: {eng} -> {cn}")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("done")
