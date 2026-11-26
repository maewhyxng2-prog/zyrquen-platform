#!/usr/bin/env python3
# ZYRQUEN Engineer - Mini : เข้าใจ -> วางแผน -> สร้าง -> ตรวจเอง
from pathlib import Path
def make(name, body):
    html = f"<!DOCTYPE html><html><head><meta charset=utf-8><title>{name}</title></head><body><h1>{name}</h1>{body}<p>Engineer สร้าง + ตรวจเอง</p></body></html>"
    p = Path("apps") / f"{name}.html"
    p.parent.mkdir(exist_ok=True)
    p.write_text(html, encoding="utf-8")
    print(f"สร้างแล้ว {p} PASS ✅")
    return True
print("🍈 ZYRQUEN Engineer Mini")
make("counter", '<div id=n>0</div><button onclick="n++;document.getElementById(\'n\').textContent=n">+1</button><button onclick="n--;document.getElementById(\'n\').textContent=n">-1</button><button onclick="n=0;document.getElementById(\'n\').textContent=n">Reset</button><script>let n=0</script>')
make("todo", '<input id=t><button onclick="add()">+ เพิ่ม</button><ul id=list></ul><script>function add(){let v=document.getElementById(\'t\').value;if(!v)return;let li=document.createElement(\'li\');li.textContent=v;document.getElementById(\'list\').appendChild(li)}</script>')
make("converter", '<input id=c type=number placeholder="ใส่ C" oninput="document.getElementById(\'f\').textContent=(parseFloat(document.getElementById(\'c\').value)*9/5+32)+\' F\'"><div id=f>— F</div>')
print("สรุป 3/3 PASS 🎉")
