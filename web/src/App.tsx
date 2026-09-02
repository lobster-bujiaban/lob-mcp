import { FormEvent, useCallback, useEffect, useState } from "react";

type Server = { id:string; name:string; transport:string; endpoint?:string; enabled:boolean };
type Invocation = { id:string; capability_name:string; status:string; trace_id:string; duration_ms?:number; started_at:string; error_message?:string };

async function api<T>(path:string, options?:RequestInit):Promise<T> {
  const response = await fetch(path, { headers:{"Content-Type":"application/json"}, ...options });
  if (!response.ok) throw new Error(await response.text());
  return response.status === 204 ? undefined as T : response.json();
}

export default function App() {
  const [servers,setServers]=useState<Server[]>([]), [invocations,setInvocations]=useState<Invocation[]>([]);
  const [orderId,setOrderId]=useState("ORD-20250902-001"), [result,setResult]=useState<unknown>();
  const [busy,setBusy]=useState(false), [error,setError]=useState("");
  const refresh=useCallback(async()=>{try{const [s,i]=await Promise.all([api<Server[]>("/api/servers"),api<Invocation[]>("/api/invocations")]);setServers(s);setInvocations(i);setError("");}catch(e){setError(String(e));}},[]);
  useEffect(()=>{void refresh();},[refresh]);
  const callOrder=async(event:FormEvent)=>{event.preventDefault();setBusy(true);setError("");try{const data=await api<unknown>("/api/tools/call",{method:"POST",body:JSON.stringify({name:"order.query",arguments:{order_id:orderId}})});setResult(data);await refresh();}catch(e){setError(String(e));}finally{setBusy(false);}};
  return <main>
    <header><div><span className="eyebrow">LOB AI 源码研究</span><h1>MCP 运行控制台</h1></div><button className="secondary" onClick={()=>void refresh()}>刷新数据</button></header>
    {error&&<div className="error">{error}</div>}
    <section className="metrics"><Metric label="Server 配置" value={servers.length}/><Metric label="可用 Server" value={servers.filter(x=>x.enabled).length}/><Metric label="调用记录" value={invocations.length}/><Metric label="失败调用" value={invocations.filter(x=>x.status==="failed").length}/></section>
    <div className="grid">
      <section className="panel"><Title title="Server 注册表" sub="配置保留，删除采用软删除"/><div className="table-wrap"><table><thead><tr><th>名称</th><th>Transport</th><th>状态</th></tr></thead><tbody>{servers.length?servers.map(x=><tr key={x.id}><td><strong>{x.name}</strong><small>{x.endpoint||"本地子进程"}</small></td><td><code>{x.transport}</code></td><td><Status value={x.enabled?"enabled":"disabled"}/></td></tr>):<Empty span={3} text="尚未注册 Server"/>}</tbody></table></div></section>
      <section className="panel tool-panel"><Title title="在线调用" sub="调用 order.query 并写入审计"/><form onSubmit={callOrder}><label>订单号<input value={orderId} onChange={e=>setOrderId(e.target.value)}/></label><button disabled={busy}>{busy?"调用中…":"执行工具"}</button></form><pre>{result?JSON.stringify(result,null,2):"等待调用结果"}</pre></section>
    </div>
    <section className="panel"><Title title="调用审计" sub="最近 100 条 Invocation"/><div className="table-wrap"><table><thead><tr><th>时间</th><th>能力</th><th>状态</th><th>耗时</th><th>Trace</th></tr></thead><tbody>{invocations.length?invocations.map(x=><tr key={x.id} title={x.error_message}><td>{new Date(x.started_at).toLocaleString()}</td><td><strong>{x.capability_name}</strong></td><td><Status value={x.status}/></td><td>{x.duration_ms?.toFixed(1)??"—"} ms</td><td><code>{x.trace_id.slice(0,12)}</code></td></tr>):<Empty span={5} text="尚无调用记录"/>}</tbody></table></div></section>
  </main>;
}
function Metric({label,value}:{label:string;value:number}){return <div className="metric"><span>{label}</span><strong>{value}</strong></div>}
function Status({value}:{value:string}){return <span className={`status ${value}`}>{value}</span>}
function Title({title,sub}:{title:string;sub:string}){return <div className="panel-title"><h2>{title}</h2><p>{sub}</p></div>}
function Empty({span,text}:{span:number;text:string}){return <tr><td colSpan={span} className="empty">{text}</td></tr>}
