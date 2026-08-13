from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>Mock OGE</title>
<style>
body{margin:0;font-family:Arial}.monaco-editor{width:520px;height:317px;border:1px solid #ccc;position:relative}
.inputarea{position:absolute;top:0;left:0;width:1px;height:1px}.console_oge_console__d89n8{width:520px;height:220px;overflow:auto;border:1px solid #ccc}
canvas{border:1px solid #aaa}.controlButton_oge_editor_control_btn__zdkQg{display:inline-flex;cursor:pointer;padding:8px;gap:4px}
</style></head><body>
<div class="monaco-editor no-user-select vs" role="code" data-uri="inmemory://model/2">
  <div class="view-lines monaco-mouse-cursor-text"></div>
  <textarea data-mprt="6" class="inputarea monaco-mouse-cursor-text" aria-label="Editor content;Press Alt+F1 for Accessibility Options." role="textbox"></textarea>
</div>
<div class="controlButton_oge_editor_control_btn__zdkQg" id="runBtn">
  <div class="controlButton_icon__FnVMg"><img alt="icon" src="/svgs/run.svg"></div>
  <div class="controlButton_text__sDKFR"><div>运行</div></div>
</div>
<div class="console_oge_console__d89n8"></div>
<canvas style="image-rendering: pixelated;" width="520" height="405"></canvas>
<script>
(()=>{
window.__modelValue = 'initial';
const model = {
  uri:{toString:()=> 'inmemory://model/2'},
  setValue:(v)=>{window.__modelValue=v; document.querySelector('.view-lines').textContent=v;},
  getValue:()=>window.__modelValue
};
window.monaco = {editor:{getModels:()=>[model]}};
function addLog(type,text){
  const root=document.querySelector('.console_oge_console__d89n8');
  const d=document.createElement('div'); d.className='console_entry__W_j9_'; d.dataset.type=type;
  d.innerHTML='<span class="console_time__YYHxL">00:00:00</span><span class="console_type__3yE4e">['+type+'] </span><span class="console_content__vt_mv"></span>';
  d.querySelector('.console_content__vt_mv').textContent=text; root.appendChild(d);
}
async function run(){
  addLog('info','正在执行python代码模版，等待服务端推送结果...');
  if(window.__modelValue.includes('ERROR_WORD_ONLY')) addLog('info','Spatial Error Model: standard error = 0.12');
  if(window.__modelValue.includes('CONSOLE_FAIL')) { addLog('error','Traceback (most recent call last): RuntimeError: mock'); return; }
  const r=await fetch('https://mock.oge/api/computation-api/executeCode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:window.__modelValue,userId:'mock',sampleName:''})});
  const data=await r.json();
  const dagIds=Object.values(data.dags||{});
  const reqs=dagIds.map(id=>fetch('https://mock.oge/api/computation-api/executeDag?level=5&dagId='+encodeURIComponent(id)+'&userId=mock',{method:'POST'}).then(x=>x.json()));
  if(window.__modelValue.includes('SUCCESS_BEFORE_DAGS')) addLog('success','运行成功');
  const results=await Promise.all(reqs);
  const c=document.querySelector('canvas'); const ctx=c.getContext('2d');
  if(results.some(x=>x.status==='success')){ctx.fillStyle='rgb(200,20,20)';ctx.fillRect(20,20,280,220);}
  if(!window.__modelValue.includes('SUCCESS_BEFORE_DAGS')) addLog('success','运行成功');
}
document.getElementById('runBtn').addEventListener('click',run);
})();
</script></body></html>'''


def install_mock_routes(page):
    def handler(route, request):
        parsed = urlparse(request.url)
        if parsed.path == "/api/computation-api/executeCode":
            req = json.loads(request.post_data or "{}")
            code = req.get("code", "")
            if "LOG_ONLY" in code:
                payload = {"spaceParams": {}, "log": "mock numeric result=42", "dags": {}}
            elif "DAG_FAIL" in code:
                payload = {"spaceParams": {}, "log": "", "dags": {"ok": "dag-ok", "bad": "dag-fail"}}
            elif "SUCCESS_BEFORE_DAGS" in code:
                payload = {"spaceParams": {}, "log": "", "dags": {"a": "dag-slow-1", "b": "dag-slow-2", "c": "dag-slow-3"}}
            else:
                payload = {"spaceParams": {}, "log": "", "dags": {"a": "dag-1", "b": "dag-2", "c": "dag-3"}}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
            return
        if parsed.path == "/api/computation-api/executeDag":
            dag_id = (parse_qs(parsed.query).get("dagId") or [""])[0]
            if dag_id.startswith("dag-slow"):
                time.sleep(0.35)
            payload = {"status": "failed", "message": "mock dag failure"} if dag_id == "dag-fail" else {
                "status": "success", "vector": [{"mock": f"/{dag_id}.json"}]
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
            return
        route.fulfill(status=200, content_type="text/plain", body="ok")

    page.route("https://mock.oge/**", handler)


def find_browser_executable() -> str | None:
    for name in ("chromium", "chromium-browser", "msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def playwright_chromium_ready(playwright) -> bool:
    try:
        return Path(playwright.chromium.executable_path).exists()
    except Exception:
        return False
