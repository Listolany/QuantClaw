# -*- coding: utf-8 -*-
"""全流程量化策略工作台 - 需求→策略→回测→结果 实时监控"""
import sys, os, json, time, threading, argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = False

STATE = {"run_id": "", "status": "waiting", "stage": "", "pct": 0, "dates": [], "points": [],
    "stats": {}, "logs": [], "done": False, "steps": {}, "requirement": {}, "code": "",
    "code_file": "", "final": None, "trades": None, "report_urls": {}, "error": None}
LOCK = threading.Lock()
CLIENTS = []

def broadcast(event, data):
    msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
    with LOCK:
        dead = []
        for wfile in CLIENTS[:]:
            try: wfile.write(msg); wfile.flush()
            except Exception: dead.append(wfile)
        for d in dead:
            try: CLIENTS.remove(d)
            except ValueError: pass

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>策略监控</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/styles/atom-one-light.min.css">
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/highlight.min.js"></script>
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/python.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:linear-gradient(180deg,#e8f4f8,#f0f9ff);min-height:100vh;color:#1e293b}
.hdr{padding:20px 32px;display:flex;align-items:center;gap:16px;background:#fff;border-bottom:1px solid #dbeafe}
.hdr h1{font-size:22px;font-weight:700;color:#1e40af}
.hdr .rid{font-size:12px;color:#64748b;font-family:monospace;margin-left:auto;background:#f1f5f9;padding:6px 14px;border-radius:8px}
.hdr .pill{padding:6px 16px;border-radius:20px;font-size:13px;font-weight:700}
.pill-w{background:#fef3c7;color:#d97706;border:1px solid #fcd34d}
.pill-r{background:#dbeafe;color:#2563eb;border:1px solid #93c5fd;animation:pulse 1.5s infinite}
.pill-s{background:#dcfce7;color:#16a34a;border:1px solid #86efac}
.pill-f{background:#fee2e2;color:#dc2626;border:1px solid #fca5a5}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}
.tl{display:flex;align-items:center;justify-content:center;padding:14px 32px;background:#fff;border-bottom:1px solid #e2e8f0;gap:0}
.tl-s{display:flex;flex-direction:column;align-items:center;gap:4px;z-index:1}
.tl-d{width:32px;height:32px;border-radius:50%;background:#e2e8f0;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#94a3b8;transition:all .3s}
.tl-d.run{background:#dbeafe;color:#2563eb;animation:pulse 1.5s infinite}
.tl-d.ok{background:#dcfce7;color:#16a34a}
.tl-d.err{background:#fee2e2;color:#dc2626}
.tl-t{font-size:11px;color:#64748b;font-weight:600;white-space:nowrap}
.tl-ln{flex:1;height:2px;background:#e2e8f0;min-width:48px;transition:background .3s}
.tl-ln.ok{background:#86efac}
.rpt-ban{display:none;padding:14px 32px;background:linear-gradient(90deg,#dcfce7,#d1fae5);border-bottom:1px solid #86efac;text-align:center;font-size:14px;font-weight:600;color:#166534}
.rpt-ban a{color:#1e40af;text-decoration:underline;margin-left:12px;font-weight:700}
.err-card{display:none;margin:0 auto 20px;max-width:1200px;padding:0 20px}
.err-inner{background:linear-gradient(135deg,#fef2f2,#fff1f2);border:2px solid #fca5a5;border-radius:16px;padding:24px;box-shadow:0 4px 16px rgba(220,38,38,.1)}
.err-inner h3{color:#dc2626;font-size:18px;font-weight:800;margin-bottom:8px;display:flex;align-items:center;gap:8px}
.err-type{display:inline-block;background:#dc2626;color:#fff;font-size:11px;padding:3px 10px;border-radius:6px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.err-msg{color:#7f1d1d;font-size:14px;margin:12px 0;line-height:1.6}
.err-tb{background:#1e1e1e;color:#f1f5f9;font-size:12px;padding:14px;border-radius:10px;max-height:200px;overflow:auto;font-family:'Cascadia Code','Fira Code',monospace;line-height:1.5;margin:12px 0;display:none}
.err-toggle{background:none;border:1px solid #fca5a5;color:#dc2626;padding:6px 14px;border-radius:8px;cursor:pointer;font-size:12px;font-weight:600}
.err-toggle:hover{background:#fee2e2}
.err-guide{margin-top:16px;padding:14px;background:#fff;border-radius:10px;border:1px solid #e2e8f0;color:#475569;font-size:13px;line-height:1.6}
.err-guide strong{color:#1e293b}
.wrap{max-width:1200px;margin:0 auto;padding:24px 20px}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:16px;margin-bottom:20px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.card-h{padding:16px 20px;display:flex;align-items:center;gap:12px;background:#f8fafc;border-bottom:1px solid #e2e8f0}
.card-h .title{font-size:16px;font-weight:700;color:#1e293b}
.card-h .badge{margin-left:auto;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}
.card-b{padding:20px}
.card-b.empty{color:#94a3b8;font-style:italic;font-size:14px;text-align:center;padding:40px 20px}
.req-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}
.req-item{background:#f8fafc;border-radius:10px;padding:14px;border:1px solid #e2e8f0}
.req-item .k{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;font-weight:600}
.req-item .v{font-size:14px;font-weight:600;margin-top:6px;color:#1e293b}
.code-wrap{background:#fafafa;border-radius:12px;border:1px solid #e2e8f0;overflow:hidden}
.code-h{padding:12px 16px;background:#f1f5f9;border-bottom:1px solid #e2e8f0;font-size:12px;color:#64748b;display:flex;align-items:center;gap:8px}
.code-h svg{width:16px;height:16px}
pre.code-block{background:#fafafa;margin:0;padding:16px;font-size:13px;max-height:420px;overflow:auto;line-height:1.7}
pre.code-block code{font-family:'Cascadia Code','Fira Code','Consolas',monospace}
.progress-outer{height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden}
.progress-inner{height:100%;border-radius:4px;background:linear-gradient(90deg,#3b82f6,#06b6d4);transition:width .5s ease}
#chart{width:100%;height:380px}
#dailyChart{width:100%;height:280px}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.sc{background:#f8fafc;border-radius:12px;padding:16px;text-align:center;border:1px solid #e2e8f0;transition:transform .15s}
.sc:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.06)}
.sc .lb{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;font-weight:600}
.sc .vl{font-size:22px;font-weight:800;margin-top:6px}
.sc .vl.pos{color:#16a34a}.sc .vl.neg{color:#dc2626}.sc .vl.neu{color:#475569}
.trade-table{width:100%;border-collapse:collapse;font-size:13px}
.trade-table th{background:#f8fafc;color:#64748b;font-weight:600;text-align:left;padding:12px 14px;border-bottom:2px solid #e2e8f0;font-size:11px;text-transform:uppercase}
.trade-table td{padding:12px 14px;border-bottom:1px solid #f1f5f9;color:#1e293b}
.trade-table tr:hover{background:#f8fafc}
.trade-table .buy{color:#16a34a;font-weight:600}.trade-table .sell{color:#dc2626;font-weight:600}
.page-nav{display:flex;justify-content:center;gap:8px;margin-top:16px}
.page-nav button{padding:8px 14px;border:1px solid #e2e8f0;background:#fff;border-radius:8px;cursor:pointer;font-size:13px;color:#475569}
.page-nav button:hover{background:#f1f5f9}
.page-nav button.active{background:#3b82f6;color:#fff;border-color:#3b82f6}
.page-nav button:disabled{opacity:.4;cursor:not-allowed}
.log-box{background:#f8fafc;border-radius:12px;padding:14px;max-height:140px;overflow-y:auto;font-size:11.5px;font-family:'Cascadia Code','Fira Code',monospace;color:#64748b;border:1px solid #e2e8f0}
</style></head><body>
<div class="hdr">
  <div style="font-size:28px">📊</div><h1>量化策略监控</h1>
  <span class="rid" id="rid">-</span>
  <span class="pill pill-w" id="gpill">等待启动</span>
</div>
<div class="tl">
  <div class="tl-s"><div class="tl-d" id="td1">1</div><div class="tl-t">需求确认</div></div>
  <div class="tl-ln" id="tln1"></div>
  <div class="tl-s"><div class="tl-d" id="td2">2</div><div class="tl-t">策略生成</div></div>
  <div class="tl-ln" id="tln2"></div>
  <div class="tl-s"><div class="tl-d" id="td3">3</div><div class="tl-t">回测执行</div></div>
  <div class="tl-ln" id="tln3"></div>
  <div class="tl-s"><div class="tl-d" id="td4">4</div><div class="tl-t">结果展示</div></div>
</div>
<div class="rpt-ban" id="rptBan">✅ 回测完成 <a id="rptLink" href="#" target="_blank">查看完整报告 →</a></div>
<div class="err-card" id="errCard"><div class="err-inner">
  <h3>⚠️ 执行失败 <span class="err-type" id="errType">ERROR</span></h3>
  <div class="err-msg" id="errMsg"></div>
  <button class="err-toggle" onclick="var t=document.getElementById('errTb');t.style.display=t.style.display==='none'?'block':'none'">展开详细堆栈</button>
  <div class="err-tb" id="errTb"></div>
  <div class="err-guide"><strong>如何处理？</strong><br>请回到对话页输入「查看结果」，AI 将为您诊断错误原因并尝试修复。<br>您也可以输入「重新生成」让 AI 重新生成策略代码。</div>
</div></div>
<div class="wrap">
  <div class="card" id="p1">
    <div class="card-h"><span class="title">📋 策略描述</span><span class="badge pill-w" id="b1">等待</span></div>
    <div class="card-b empty" id="c1">等待策略描述...</div>
  </div>
  <div class="card" id="p2">
    <div class="card-h"><span class="title">💻 策略代码</span><span class="badge pill-w" id="b2">等待</span></div>
    <div class="card-b empty" id="c2">等待策略代码生成...</div>
  </div>
  <div class="card" id="p3">
    <div class="card-h"><span class="title">📈 收益曲线图</span><span class="badge pill-w" id="b3">等待</span></div>
    <div class="card-b"><div class="progress-outer"><div class="progress-inner" id="bar3" style="width:0%"></div></div><div id="chart"></div></div>
  </div>
  <div class="card" id="p4">
    <div class="card-h"><span class="title">📊 每日收益图</span><span class="badge pill-w" id="b4">等待</span></div>
    <div class="card-b"><div id="dailyChart"></div></div>
  </div>
  <div class="card" id="p5">
    <div class="card-h"><span class="title">📉 回测结果统计</span><span class="badge pill-w" id="b5">等待</span></div>
    <div class="card-b empty" id="c5">等待回测完成...</div>
  </div>
  <div class="card" id="p6">
    <div class="card-h"><span class="title">📝 交易记录</span></div>
    <div class="card-b" id="c6"><div class="empty">暂无交易记录</div></div>
    <div class="page-nav" id="pageNav" style="display:none"></div>
  </div>
  <div style="font-size:12px;color:#64748b;padding:0 4px;margin-top:16px">
    <strong>📌 日志</strong>
    <div class="log-box" id="logs">系统就绪，等待连接...</div>
  </div>
</div>
<script>
const RID=location.pathname.split('/').pop()||'';
document.getElementById('rid').textContent='run: '+RID;
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function setBadge(id,st){const e=document.getElementById(id);if(!e)return;e.className='badge '+({running:'pill-r',success:'pill-s',failed:'pill-f'}[st]||'pill-w');e.textContent={pending:'等待',running:'进行中',success:'完成',failed:'失败'}[st]||st}
function setTL(n,st){
  const map={1:[1],2:[2],3:[2],4:[3],5:[4],9:[4]};
  (map[n]||[]).forEach(d=>{const el=document.getElementById('td'+d);if(!el)return;
    if(st==='running'){el.className='tl-d run'}
    else if(st==='success'){el.className='tl-d ok';el.textContent='✓';const ln=document.getElementById('tln'+d);if(ln)ln.className='tl-ln ok'}
    else if(st==='failed'){el.className='tl-d err';el.textContent='✗'}
  })
}
function addLog(m){const e=document.getElementById('logs');e.innerHTML+='<div>['+new Date().toLocaleTimeString()+'] '+m+'</div>';e.scrollTop=e.scrollHeight}
const chart=echarts.init(document.getElementById('chart'),null,{renderer:'canvas'});
const dailyChart=echarts.init(document.getElementById('dailyChart'),null,{renderer:'canvas'});
const chartOpt={animation:true,animationDuration:300,animationEasing:'cubicOut',
  tooltip:{trigger:'axis',backgroundColor:'rgba(255,255,255,.98)',borderColor:'#e2e8f0',textStyle:{color:'#1e293b',fontSize:13},padding:[10,14],shadowBlur:8,shadowColor:'rgba(0,0,0,.1)'},
  legend:{data:['策略净值','沪深 300 基准'],top:10,right:16,textStyle:{color:'#64748b',fontSize:12}},
  grid:{left:64,right:32,top:52,bottom:48},
  xAxis:{type:'category',data:[],axisLabel:{color:'#94a3b8',fontSize:11,rotate:0},axisLine:{lineStyle:{color:'#e2e8f0'}},boundaryGap:false},
  yAxis:{type:'value',name:'净值',nameTextStyle:{color:'#64748b',fontSize:12},axisLabel:{color:'#64748b',fontSize:11,formatter:v=>v.toFixed(2)},axisLine:{lineStyle:{color:'#e2e8f0'}},splitLine:{lineStyle:{color:'#f1f5f9'}},min:'dataMin'},
  series:[
    {name:'策略净值',type:'line',data:[],smooth:.25,lineStyle:{width:3,color:'#2563eb'},areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(37,99,235,.15)'},{offset:1,color:'rgba(37,99,235,0)'}]}},symbol:'none',symbolSize:6},
    {name:'沪深 300 基准',type:'line',data:[],smooth:.25,lineStyle:{width:2,color:'#dc2626',type:'dashed'},symbol:'none'}
  ]};
chart.setOption(chartOpt);
const dailyOpt={animation:true,animationDuration:300,
  tooltip:{trigger:'axis',backgroundColor:'rgba(255,255,255,.98)',borderColor:'#e2e8f0',textStyle:{color:'#1e293b',fontSize:13},padding:[10,14]},
  grid:{left:56,right:24,top:36,bottom:48},
  xAxis:{type:'category',data:[],axisLabel:{color:'#94a3b8',fontSize:10},axisLine:{lineStyle:{color:'#e2e8f0'}}},
  yAxis:{type:'value',name:'日收益%',nameTextStyle:{color:'#64748b'},axisLabel:{color:'#64748b',fontSize:11,formatter:v=>v.toFixed(2)+'%'},axisLine:{lineStyle:{color:'#e2e8f0'}},splitLine:{lineStyle:{color:'#f1f5f9'}}},
  series:[{name:'日收益',type:'bar',data:[],itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#16a34a'},{offset:.5,color:'#84cc16'},{offset:1,color:'#dc2626'}]}},barWidth:'60%',showBackground:true,backgroundStyle:{color:'rgba(0,0,0,.02)'}}]};
dailyChart.setOption(dailyOpt);
window.addEventListener('resize',()=>{chart.resize();dailyChart.resize()});
let dateIdx={},tradeData=[],currentPage=1,pageSize=10;
function renderTrades(){
  const start=(currentPage-1)*pageSize,end=start+pageSize;
  const page=tradeData.slice(start,end);
  let h='<table class="trade-table"><thead><tr><th>日期</th><th>方向</th><th>价格</th><th>数量</th><th>金额</th></tr></thead><tbody>';
  page.forEach(t=>{const isBuy=t.direction==='买入'||t.direction==='BUY';const cls=isBuy?'buy':'sell';const dir=isBuy?'买入':'卖出';h+='<tr><td>'+t.date+'</td><td class="'+cls+'">'+dir+'</td><td>'+t.price+'</td><td>'+t.volume+'</td><td>'+t.amount+'</td></tr>'});
  h+='</tbody></table>';document.getElementById('c6').innerHTML=h||'<div class="empty">暂无交易记录</div>';
  const total=Math.ceil(tradeData.length/pageSize);
  const nav=document.getElementById('pageNav');
  if(total>1){nav.style.display='flex';let p='';for(let i=1;i<=total;i++)p+='<button class="'+(i===currentPage?'active':'')+'" onclick="currentPage='+i+',renderTrades()">'+i+'</button>';nav.innerHTML=p}
  else nav.style.display='none'
}
const es=new EventSource('/api/sse?run_id='+RID);
es.addEventListener('step',e=>{const d=JSON.parse(e.data);addLog('['+d.step+'] '+d.title+': '+(d.msg||d.status));
  const sn=parseInt(d.step)||0;setTL(sn,d.status);
  if(sn<=2){setBadge('b1',d.status);if(d.status==='running'){const g=document.getElementById('gpill');g.className='pill pill-r';g.textContent='执行中'}}
  if(sn===3||d.step.includes('3')){setBadge('b2',d.status)}
  if(sn>=4){setBadge('b3',d.status)}
});
es.addEventListener('requirement',e=>{const d=JSON.parse(e.data);setBadge('b1','success');
  const el=document.getElementById('c1');el.classList.remove('empty');
  let h='<div class="req-grid">';for(const[k,v] of Object.entries(d))h+='<div class="req-item"><div class="k">'+k+'</div><div class="v">'+v+'</div></div>';
  el.innerHTML=h+'</div>'});
es.addEventListener('code',e=>{const d=JSON.parse(e.data);setBadge('b2','success');
  const el=document.getElementById('c2');el.classList.remove('empty');
  el.innerHTML='<div class="code-wrap"><div class="code-h"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>📄 '+(d.filename||'strategy.py')+' · 已保存至绝对路径</div><pre class="code-block"><code class="language-python">'+esc(d.content)+'</code></pre></div>';
  hljs.highlightAll()});
es.addEventListener('progress',e=>{const d=JSON.parse(e.data);
  if(d.run_id)document.getElementById('rid').textContent='run: '+d.run_id;
  const pct=parseInt(d.pct)||0;document.getElementById('bar3').style.width=pct+'%';
  if(d.status==='running'||pct>0){setBadge('b3',d.status||'running')}
  if(d.status==='failed'){setBadge('b3','failed');const g=document.getElementById('gpill');g.className='pill pill-f';g.textContent='失败'}
});
es.addEventListener('init_axis',e=>{const d=JSON.parse(e.data);dateIdx={};
  chartOpt.xAxis.data=d.dates;chartOpt.series[0].data=new Array(d.dates.length).fill(null);chartOpt.series[1].data=new Array(d.dates.length).fill(null);
  d.dates.forEach((dt,i)=>dateIdx[dt]=i);chart.setOption(chartOpt,true);setBadge('b3','running')});
es.addEventListener('point',e=>{const d=JSON.parse(e.data);
  const i=dateIdx[d.dt];if(i!==undefined){chartOpt.series[0].data[i]=parseFloat(d.nav)}
  else{chartOpt.xAxis.data.push(d.dt);chartOpt.series[0].data.push(parseFloat(d.nav));chartOpt.series[1].data.push(null)}
  chart.setOption(chartOpt)});
es.addEventListener('final_chart',e=>{const d=JSON.parse(e.data);
  chartOpt.xAxis.data=d.dates;chartOpt.series[0].data=d.navs;chartOpt.series[1].data=d.bench||[];
  chart.setOption(chartOpt,true);setBadge('b3','success');document.getElementById('bar3').style.width='100%';
  const daily=[];const dailyDates=[];
  for(let i=1;i<d.navs.length&&i<d.dates.length;i++){
    const prev=d.navs[i-1]||1,curr=d.navs[i];
    daily.push(((curr-prev)/prev*100).toFixed(3));
    dailyDates.push(d.dates[i]);
  }
  dailyOpt.xAxis.data=dailyDates;dailyOpt.series[0].data=daily.map(v=>parseFloat(v));dailyChart.setOption(dailyOpt,true);
  setBadge('b4','success')});
es.addEventListener('stats',e=>{const d=JSON.parse(e.data);setBadge('b5','success');
  const el=document.getElementById('c5');el.classList.remove('empty');
  const fmt={total_return:['总收益率',true],annual_return:['年化收益',true],max_ddpercent:['最大回撤',true],sharpe_ratio:['夏普比率',true],total_trade_count:['交易次数',false],total_days:['交易天数',false],profit_days:['盈利天数',false],loss_days:['亏损天数',false]};
  let h='<div class="stats-grid">';for(const[k,[lb,isPct]] of Object.entries(fmt)){const v=d[k];if(v===undefined)continue;
    const n=typeof v==='number';let disp=n?(isPct?v.toFixed(2)+'%':v.toFixed(4)):v;
    const c=n?(v>=0?'pos':'neg'):'neu';
    h+='<div class="sc"><div class="lb">'+lb+'</div><div class="vl '+c+'">'+disp+'</div></div>'}
  el.innerHTML=h+'</div>'});
es.addEventListener('trades',e=>{const d=JSON.parse(e.data);tradeData=d.trades||[];currentPage=1;renderTrades()});
es.addEventListener('log',e=>{const d=JSON.parse(e.data);addLog(d.msg||'')});
es.addEventListener('done',e=>{const g=document.getElementById('gpill');g.className='pill pill-s';g.textContent='已完成';
  setBadge('b3','success');setBadge('b5','success');setTL(5,'success');addLog('✅ 全部完成')});
es.addEventListener('report_urls',e=>{const d=JSON.parse(e.data);const url=d.report_url||'';
  if(url){document.getElementById('rptLink').href=url;document.getElementById('rptBan').style.display='block'}});
es.addEventListener('error_info',e=>{const d=JSON.parse(e.data);
  document.getElementById('errCard').style.display='block';
  document.getElementById('errType').textContent=(d.error_type||'ERROR').toUpperCase();
  document.getElementById('errMsg').textContent=(d.step?'['+d.step+'] ':'')+d.message;
  if(d.traceback){document.getElementById('errTb').textContent=d.traceback}
  const g=document.getElementById('gpill');g.className='pill pill-f';g.textContent='失败';
  addLog('❌ '+d.error_type+': '+d.message)});
es.onerror=()=>{addLog('⚠️ 连接断开，自动重连...')};
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = urlparse(self.path).path; qs = parse_qs(urlparse(self.path).query)
        if path == "/" or path.startswith("/runs/"):
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write(HTML_PAGE.encode())
        elif path == "/api/sse" or path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
            with LOCK: CLIENTS.append(self.wfile)
            with LOCK: s = dict(STATE)
            self._sse_send("progress", s)
            if s.get("requirement"): self._sse_send("requirement", s["requirement"])
            if s.get("code"): self._sse_send("code", {"filename": s["code_file"], "content": s["code"]})
            if s.get("dates"): self._sse_send("init_axis", {"dates": s["dates"]})
            for pt in s.get("points", []): self._sse_send("point", pt)
            if s.get("final"): self._sse_send("final_chart", s["final"])
            if s.get("stats"): self._sse_send("stats", s["stats"])
            if s.get("trades") is not None: self._sse_send("trades", {"trades": s["trades"]})
            if s.get("report_urls"): self._sse_send("report_urls", s["report_urls"])
            if s.get("error"): self._sse_send("error_info", s["error"])
            for st in s.get("steps", {}).values(): self._sse_send("step", st)
            if s.get("done"): self._sse_send("done", {})
            self.wfile.flush()
            try:
                while not STATE["done"]: time.sleep(1)
                time.sleep(5)
            except Exception: pass
        elif path == "/api/step":
            self._json_ok()
            d = {"step": qs.get("step",[""])[0], "status": qs.get("status",["running"])[0], "title": qs.get("title",[""])[0], "msg": qs.get("msg",[""])[0]}
            with LOCK: STATE["steps"][d["step"]] = d; STATE["run_id"] = qs.get("run_id", [STATE["run_id"]])[0]
            broadcast("step", d)
        elif path == "/api/progress":
            self._json_ok()
            with LOCK:
                STATE["run_id"] = qs.get("run_id", [STATE["run_id"]])[0]; STATE["status"] = qs.get("status", [STATE["status"]])[0]
                STATE["stage"] = qs.get("stage", [STATE["stage"]])[0]; STATE["pct"] = int(qs.get("pct", [STATE["pct"]])[0])
            broadcast("progress", STATE)
        elif path == "/api/point":
            self._json_ok()
            pt = {"dt": qs.get("dt",[""])[0], "nav": float(qs.get("nav",[1])[0])}
            with LOCK: STATE["points"].append(pt)
            broadcast("point", pt)
        elif path == "/api/stats":
            self._json_ok()
            stats = {}
            for k, v in qs.items():
                try: stats[k] = float(v[0])
                except Exception: stats[k] = v[0]
            with LOCK: STATE["stats"] = stats
            broadcast("stats", stats)
        elif path == "/api/trades":
            self._json_ok()
            trades = json.loads(qs.get("data", ["[]"])[0])
            with LOCK: STATE["trades"] = trades
            broadcast("trades", {"trades": trades})
        elif path == "/api/log":
            self._json_ok()
            msg = qs.get("msg",[""])[0]
            with LOCK: STATE["logs"].append(msg)
            broadcast("log", {"msg": msg})
        elif path == "/api/done":
            self._json_ok()
            with LOCK: STATE["done"] = True; STATE["status"] = "done"; STATE["pct"] = 100
            broadcast("done", {}); broadcast("progress", STATE)
        elif path == "/api/health":
            self._json_ok()
        else:
            self.send_response(404); self.end_headers()
    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        data = json.loads(body) if body else {}
        if path == "/api/requirement":
            self._json_ok()
            with LOCK: STATE["requirement"] = data
            broadcast("requirement", data)
        elif path == "/api/code":
            self._json_ok()
            with LOCK: STATE["code"] = data.get("content", ""); STATE["code_file"] = data.get("filename", "strategy.py")
            broadcast("code", data)
        elif path == "/api/init_axis":
            self._json_ok()
            with LOCK: STATE["dates"] = data.get("dates", [])
            broadcast("init_axis", data)
        elif path == "/api/final":
            self._json_ok()
            with LOCK: STATE["final"] = data
            broadcast("final_chart", data)
        elif path == "/api/trades":
            self._json_ok()
            with LOCK: STATE["trades"] = data.get("trades", [])
            broadcast("trades", data)
        elif path == "/api/report_urls":
            self._json_ok()
            with LOCK: STATE["report_urls"] = data
            broadcast("report_urls", data)
        elif path == "/api/error":
            self._json_ok()
            with LOCK: STATE["error"] = data
            broadcast("error_info", data)
        else:
            self.send_response(404); self.end_headers()
    def _json_ok(self):
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
        self.wfile.write(b'{"ok":true}')
    def _sse_send(self, event, data):
        try: self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
        except Exception: pass

def _kill_port(port):
    import socket, subprocess
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(1)
        if s.connect_ex(("127.0.0.1", port)) != 0: s.close(); return
        s.close()
    except Exception: return
    for _ in range(3):
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command",
                f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique | ForEach-Object {{ Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }}"],
                timeout=8, capture_output=True, text=True)
        except Exception: pass
        time.sleep(1.5)
        try:
            t = socket.socket(socket.AF_INET, socket.SOCK_STREAM); t.settimeout(1)
            if t.connect_ex(("127.0.0.1", port)) != 0: t.close(); return
            t.close()
        except Exception: return
    print(f"[warn] 端口 {port} 清理 3 次仍被占用", flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--run-id", default="")
    args = ap.parse_args()
    _kill_port(args.port)
    STATE["run_id"] = args.run_id
    srv = ThreadedHTTPServer((args.host, args.port), Handler)
    shown_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"[monitor] http://{shown_host}:{args.port}/runs/{args.run_id}", flush=True)
    print(f"[monitor] pid={os.getpid()}", flush=True)
    def auto_stop():
        while not STATE["done"]: time.sleep(1)
        time.sleep(300); srv.shutdown()
    threading.Thread(target=auto_stop, daemon=True).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    srv.server_close()

if __name__ == "__main__":
    main()
