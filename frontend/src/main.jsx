import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import WebApp from '@twa-dev/sdk';
import './style.css';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const dev = import.meta.env.VITE_DEV_AUTH === 'true';
const headers = () => {
  const h = {'Content-Type':'application/json'};
  if (WebApp.initData) h['X-Telegram-Init-Data'] = WebApp.initData;
  else if (dev) h['X-Dev-Telegram-Id'] = import.meta.env.VITE_DEV_TELEGRAM_ID || '100000001';
  return h;
};
async function request(path, options={}) {
  const res = await fetch(API+path, {...options, headers:{...headers(), ...(options.headers||{})}});
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (Array.isArray(body.detail)) detail = body.detail.map(d => (d.msg || '').replace(/^Value error, /, '')).join('; ');
      else if (body.detail) detail = body.detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}
const days=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
const types=[['lecture','Лекция'],['seminar','Семинар'],['lab','Лабораторная'],['physical','Физкультура'],['exam','Экзамен'],['other','Другое']];
const parityLabels={both:'Обе недели',odd:'Нечётная',even:'Чётная'};
function App(){
 const [tab,setTab]=useState('plan'), [plan,setPlan]=useState(null), [lessons,setLessons]=useState([]), [rules,setRules]=useState([]), [me,setMe]=useState(null), [err,setErr]=useState(''), [day,setDay]=useState('today'), [parity,setParity]=useState('both'), [parseGroup,setParseGroup]=useState(''), [parsing,setParsing]=useState(false);
 const [weather,setWeather]=useState(null), [weatherLoading,setWeatherLoading]=useState(false);
 const [agentChats,setAgentChats]=useState([]), [facts,setFacts]=useState([]), [monitors,setMonitors]=useState([]), [agentQuestion,setAgentQuestion]=useState(''), [agentAnswer,setAgentAnswer]=useState(''), [monitorText,setMonitorText]=useState(''), [agentChat,setAgentChat]=useState(''), [agentDetail,setAgentDetail]=useState('normal');
 const [aiSettings,setAiSettings]=useState(null);
 const [lesson,setLesson]=useState({subject:'',lesson_type:'lecture',weekday:new Date().getDay()===0?6:new Date().getDay()-1,start_time:'09:00',end_time:'10:30',room:'',campus:'',week_parity:'both',notes:''});
 const [rule,setRule]=useState({match_type:'always',match_value:'',items:''});
 async function refresh(){
   try { setErr(''); const [p,l,r,m,par]=await Promise.all([request('/api/plan?day='+day),request('/api/lessons'),request('/api/bag-rules'),request('/api/me'),request('/api/week-parity')]); setPlan(p);setLessons(l);setRules(r);setMe(m);setParity(par.parity||'both'); }
   catch(e){setErr(e.message+' — проверьте запуск backend и авторизацию Mini App.');}
 }
 useEffect(()=>{try{WebApp.ready();WebApp.expand();}catch{} refresh();},[day]);
 async function loadWeather(){setWeatherLoading(true);try{setErr('');setWeather(await request('/api/weather'));}catch(e){setErr(e.message)}finally{setWeatherLoading(false)}}
 useEffect(()=>{if(tab==='weather')loadWeather();},[tab]);
 async function loadAgent(){try{const [c,f,m,s]=await Promise.all([request('/api/agent/chats'),request('/api/agent/facts'),request('/api/agent/monitors'),request('/api/agent/ai-settings')]);setAgentChats(c);setFacts(f);setMonitors(m);setAiSettings(s)}catch(e){setErr(e.message)}}
 useEffect(()=>{if(tab==='agent')loadAgent();},[tab]);
 async function askAgent(e){e.preventDefault();try{setAgentAnswer('Ищу в переписке…');const r=await request('/api/agent/chat',{method:'POST',body:JSON.stringify({message:agentQuestion,chat_ids:agentChat?[+agentChat]:[],detail:agentDetail})});setAgentAnswer(r.answer+(r.model?'\n\nМодель: '+r.model:'')+(r.sources?.filter(s=>s.link).length?'\nИсточники:\n'+r.sources.filter(s=>s.link).slice(0,5).map(s=>s.link).join('\n'):''));loadAgent()}catch(e){setErr(e.message)}}
 async function addMonitor(e){e.preventDefault();try{await request('/api/agent/monitors',{method:'POST',body:JSON.stringify({query:monitorText,priority:'normal',cooldown_minutes:60})});setMonitorText('');loadAgent()}catch(e){setErr(e.message)}}
 async function addLesson(e){e.preventDefault();try{await request('/api/lessons',{method:'POST',body:JSON.stringify(lesson)});setLesson({...lesson,subject:''});refresh();}catch(e){setErr(e.message)}}
 async function addRule(e){e.preventDefault();try{await request('/api/bag-rules',{method:'POST',body:JSON.stringify(rule)});setRule({...rule,items:''});refresh();}catch(e){setErr(e.message)}}
 async function parseSchedule(e){e&&e.preventDefault();setParsing(true);setErr('');try{const g=parseGroup.trim();console.log('[parseSchedule] started, group=',g);if(!g)throw new Error('Введите номер группы');const res=await request('/api/lessons/parse',{method:'POST',body:JSON.stringify({group_name:g})});console.log('[parseSchedule] response=',res);setErr('Расписание группы '+g+' спарсено: '+res.count+' занятий'+(res.count===0?' (занятия не найдены — проверьте номер группы)' :''));setParseGroup('');refresh();}catch(e){console.error('[parseSchedule] error=',e);setErr(e.message)}finally{setParsing(false)}}
 async function remove(path){try{await request(path,{method:'DELETE'});refresh()}catch(e){setErr(e.message)}}
 async function saveMe(e){e.preventDefault();try{if(/[A-Za-z]/.test(me.home_address||''))throw new Error('Введите город на русском языке, например: Санкт-Петербург');await request('/api/me',{method:'PATCH',body:JSON.stringify(me)});setErr('Настройки сохранены');}catch(e){setErr(e.message)}}
 return <main>
  <header><div className="logo">🎓 StudyPilot</div><div className="sub">Твой учебный день под контролем</div></header>
  <nav>{[['plan','План'],['schedule','Расписание'],['weather','Погода'],['bag','Рюкзак'],['agent','AI'],['settings','Настройки']].map(([id,label])=><button className={tab===id?'active':''} onClick={()=>setTab(id)} key={id}>{label}</button>)}</nav>
  {err&&<div className="alert" style={{color:'#c0392b',fontWeight:600,padding:'10px',background:'#fdecea',borderRadius:'8px',margin:'10px 0'}}>{err}</div>}
  {tab==='plan'&&<section><div className="row"><h2>План дня</h2><select value={day} onChange={e=>setDay(e.target.value)}><option value="today">Сегодня</option><option value="tomorrow">Завтра</option></select></div>
    {plan&&<><p className="muted">{plan.weekday} · {plan.date}</p><div className="hero"><span>🚪 Рекомендуемое время выхода</span><strong>{plan.departure_time||'—:—'}</strong><small>Дорога {plan.travel_minutes} мин. + сборы и запас</small></div>
    <h3>Занятия</h3>{plan.lessons.length?plan.lessons.map(l=><article key={l.id}><b>{l.start}–{l.end}</b><span>{l.subject}</span><small>{l.type_label} {l.room&&'· ауд. '+l.room}</small></article>):<p className="muted">Занятий нет. Добавьте расписание во вкладке «Расписание».</p>}
    <h3>🎒 Что взять</h3><div className="pilllist">{plan.bag.length?plan.bag.map(x=><span className="pill" key={x}>{x}</span>):<span className="muted">Настройте правила рюкзака.</span>}</div>
    <h3>🪟 Свободные окна</h3>{plan.windows.length?plan.windows.map((w,i)=><article key={i}><b>{w.from}–{w.to}</b><span>{w.minutes} минут</span><small>Можно пообедать или позаниматься</small></article>):<p className="muted">Длинных окон не найдено.</p>}<p className="warning">ℹ️ {plan.disclaimer}</p></>}
  </section>}
  {tab==='schedule'&&<section><h2>Расписание</h2><p className="muted">Текущая неделя: {parityLabels[parity]||parity}</p><form onSubmit={addLesson} className="panel">
    <label>Предмет<input required value={lesson.subject} onChange={e=>setLesson({...lesson,subject:e.target.value})}/></label>
    <div className="two"><label>День<select value={lesson.weekday} onChange={e=>setLesson({...lesson,weekday:+e.target.value})}>{days.map((d,i)=><option value={i} key={d}>{d}</option>)}</select></label><label>Тип<select value={lesson.lesson_type} onChange={e=>setLesson({...lesson,lesson_type:e.target.value})}>{types.map(([v,t])=><option value={v} key={v}>{t}</option>)}</select></label></div>
    <div className="two"><label>Неделя<select value={lesson.week_parity} onChange={e=>setLesson({...lesson,week_parity:e.target.value})}>{Object.entries(parityLabels).map(([v,t])=><option value={v} key={v}>{t}</option>)}</select></label></div>
    <div className="two"><label>Начало<input type="time" value={lesson.start_time} onChange={e=>setLesson({...lesson,start_time:e.target.value})}/></label><label>Конец<input type="time" value={lesson.end_time} onChange={e=>setLesson({...lesson,end_time:e.target.value})}/></label></div>
    <div className="two"><label>Аудитория<input value={lesson.room} onChange={e=>setLesson({...lesson,room:e.target.value})}/></label><label>Корпус<input value={lesson.campus} onChange={e=>setLesson({...lesson,campus:e.target.value})}/></label></div>
    <button className="primary">Добавить занятие</button></form>
    <div className="panel"><h3 style={{margin:'0 0 8px 0'}}>Спарсить расписание ГУАП по группе</h3><p className="muted">Введите номер группы. Текущие занятия будут заменены спарсенными.</p><div className="two"><label>Номер группы<input value={parseGroup} onChange={e=>setParseGroup(e.target.value)} placeholder="Например, 4414"/></label><button className="primary" onClick={parseSchedule} disabled={parsing}>{parsing?'Идёт парсинг...':'Спарсить расписание'}</button></div></div>
    {lessons.map(l=><article key={l.id}><b>{days[l.weekday]} {l.start}–{l.end}</b><span>{l.subject}</span><small>{types.find(t=>t[0]===l.type)?.[1]||l.type} · {l.room||'аудитория не указана'} · {parityLabels[l.week_parity]||l.week_parity}</small><button className="delete" onClick={()=>remove('/api/lessons/'+l.id)}>Удалить</button></article>)}
  </section>}
  {tab==='weather'&&<section><div className="row"><h2>Погода</h2><button className="primary" onClick={loadWeather} disabled={weatherLoading}>{weatherLoading?'Загрузка...':'Обновить'}</button></div>
    {weather&&!weather.available&&<div className="hint">{weather.message} <br/>Город задаётся во вкладке «Настройки».</div>}
    {weather&&weather.available&&<><p className="muted">{weather.place}{weather.region?', '+weather.region:''}</p>
    <div className="hero"><span>{weather.current.icon} {weather.current.label}</span><strong>{Math.round(weather.current.temperature)}°C</strong><small>Ощущается как {Math.round(weather.current.feels_like)}°C · ветер {weather.current.wind} м/с · влажность {weather.current.humidity}%{weather.current.precipitation>0?' · осадки '+weather.current.precipitation+' мм':''}</small></div>
    <h3>🎒 Что надеть и взять</h3><div className="pilllist">{weather.advice.map(a=><span className="pill" key={a}>{a}</span>)}</div>
    <h3>Ближайшие сутки</h3>{weather.hours.map(h=><article key={h.time}><b>{h.time}</b><span>{h.icon} {Math.round(h.temperature)}°C · {h.label}</span><small>Вероятность осадков: {h.precip_prob}%</small></article>)}
    <h3>На 3 дня</h3>{weather.days.map(d=><article key={d.date}><b>{d.weekday}, {d.date.slice(8,10)}.{d.date.slice(5,7)}</b><span>{d.icon} {Math.round(d.t_min)}…{Math.round(d.t_max)}°C · {d.label}</span><small>Вероятность осадков: {d.precip_prob}%</small></article>)}
    <p className="warning">Данные: Open-Meteo.</p></>}
    {!weather&&weatherLoading&&<p className="muted">Загружаем погоду…</p>}
  </section>}
  {tab==='bag'&&<section><h2>Правила рюкзака</h2><p className="muted">Вещи разделяйте запятыми. Примеры: зарядка, пропуск, наушники.</p><form onSubmit={addRule} className="panel">
    <label>Когда применять<select value={rule.match_type} onChange={e=>setRule({...rule,match_type:e.target.value})}><option value="always">Всегда</option><option value="type">По типу занятия</option><option value="keyword">По слову в названии</option></select></label>
    {rule.match_type!=='always'&&<label>{rule.match_type==='type'?'Тип занятия':'Ключевое слово'}{rule.match_type==='type'?<select value={rule.match_value} onChange={e=>setRule({...rule,match_value:e.target.value})}>{types.map(([v,t])=><option value={v} key={v}>{t}</option>)}</select>:<input value={rule.match_value} onChange={e=>setRule({...rule,match_value:e.target.value})} required/>}</label>}
    <label>Список вещей<input required value={rule.items} onChange={e=>setRule({...rule,items:e.target.value})} placeholder="зарядка, пропуск, наушники"/></label><button className="primary">Добавить правило</button></form>
    {rules.map(r=><article key={r.id}><b>{r.match_type==='always'?'Всегда':r.match_type==='type'?'Тип: '+(types.find(t=>t[0]===r.match_value)?.[1]||r.match_value):'Слово: '+r.match_value}</b><span>{r.items}</span><button className="delete" onClick={()=>remove('/api/bag-rules/'+r.id)}>Удалить</button></article>)}
    <div className="hint">По умолчанию физкультура добавляет форму и обувь, лабораторная — методичку и тетрадь, экзамен — студенческий билет и ручки.</div>
  </section>}
  {tab==='agent'&&<section><h2>AI-агент</h2>{aiSettings&&<div className="panel"><b>Настройки AI</b><label>Режим<select value={aiSettings.mode} onChange={async e=>{await request('/api/agent/ai-settings',{method:'PATCH',body:JSON.stringify({mode:e.target.value})});loadAgent()}}><option value="economy">Экономичный</option><option value="auto">Автоматический</option><option value="quality">Качественный</option></select></label><label><input type="checkbox" checked={aiSettings.ai_enabled} onChange={async e=>{await request('/api/agent/ai-settings',{method:'PATCH',body:JSON.stringify({ai_enabled:e.target.checked})});loadAgent()}}/> AI включён для меня</label><small>Провайдер: {aiSettings.provider} · основная: {aiSettings.primary_model} · фоновая: {aiSettings.background_model}</small><small>Статус: {aiSettings.configured?(aiSettings.provider_error?'приостановлен: '+aiSettings.provider_error:'подключён'):'ключ не настроен'} · очередь: {aiSettings.pending_messages}</small><small>За месяц: {aiSettings.usage.input_tokens+aiSettings.usage.output_tokens} токенов · примерно {aiSettings.usage.estimated_cost_rub} ₽</small></div>}<form className="panel" onSubmit={askAgent}><label>Чаты<select value={agentChat} onChange={e=>setAgentChat(e.target.value)}><option value="">Все доступные чаты</option>{agentChats.map(c=><option value={c.id} key={c.id}>{c.title}</option>)}</select></label><label>Подробность<select value={agentDetail} onChange={e=>setAgentDetail(e.target.value)}><option value="brief">Кратко</option><option value="normal">Обычно</option><option value="detailed">Подробно</option></select></label><label>Вопрос по переписке<textarea value={agentQuestion} onChange={e=>setAgentQuestion(e.target.value)} placeholder="Что решили по поводу экзамена?" required/></label><button className="primary">Спросить</button>{agentAnswer&&<pre className="agent-answer">{agentAnswer}</pre>}</form>
    <h3>Подключённые группы</h3>{agentChats.length?agentChats.map(c=><article key={c.id}><b>{c.title}</b><span>{c.analysis_enabled?'Анализ включён':'Анализ выключен'} · {c.role}</span>{['administrator','creator'].includes(c.role)&&<label><input type="checkbox" checked={c.external_ai_enabled} onChange={async e=>{await request('/api/agent/chats/'+c.id,{method:'PATCH',body:JSON.stringify({external_ai_enabled:e.target.checked})});loadAgent()}}/> Передавать сообщения внешнему AI</label>}<label>Сводки<select value={c.digest_mode} onChange={async e=>{await request('/api/agent/chats/'+c.id,{method:'PATCH',body:JSON.stringify({digest_mode:e.target.value})});loadAgent()}}><option value="off">Выключены</option><option value="daily">Ежедневно</option><option value="weekly">Еженедельно</option></select></label><label>Индивидуальные правила анализа<textarea defaultValue={c.custom_rules} placeholder="Например: особенно отмечай изменения экзаменов" onBlur={async e=>{await request('/api/agent/chats/'+c.id,{method:'PATCH',body:JSON.stringify({custom_rules:e.target.value})})}}/></label><button className="delete" onClick={async()=>{await request('/api/agent/chats/'+c.id,{method:'PATCH',body:JSON.stringify({enabled:false})});loadAgent()}}>Отключить для меня</button>{['administrator','creator'].includes(c.role)&&<button className="delete" onClick={async()=>{if(confirm('Удалить всю сохранённую историю этой группы?')){await request('/api/agent/chats/'+c.id+'/data',{method:'DELETE'});loadAgent()}}}>Удалить историю</button>}</article>):<p className="muted">Добавьте бота в группу, выполните /ai_on и затем /ai_join.</p>}
    <h3>Задачи и решения</h3>{facts.slice(0,20).map(f=><article key={f.id}><b>{f.kind} · {Math.round(f.confidence*100)}%</b><span>{f.statement}</span><small>{f.status}{f.assignee?' · '+f.assignee:''}</small></article>)}{!facts.length&&<p className="muted">Значимые факты ещё не обнаружены.</p>}
    <h3>Мониторинг</h3><form className="panel" onSubmit={addMonitor}><label>О чём сообщить<input value={monitorText} onChange={e=>setMonitorText(e.target.value)} placeholder="перенос экзамена" required/></label><button className="primary">Добавить правило</button></form>{monitors.map(m=><article key={m.id}><span>{m.query}</span><small>Пауза между уведомлениями: {m.cooldown_minutes} мин.</small><button className="delete" onClick={async()=>{await remove('/api/agent/monitors/'+m.id);loadAgent()}}>Отключить</button></article>)}
  </section>}
  {tab==='settings'&&<section><h2>Личный кабинет</h2>{me&&<form onSubmit={saveMe} className="panel">
    <label>Имя<input value={me.name} onChange={e=>setMe({...me,name:e.target.value})}/></label><label>Город (на русском языке)<input value={me.home_address} onChange={e=>setMe({...me,home_address:e.target.value})} placeholder="Например, Санкт-Петербург"/></label><label>Корпус вуза<input value={me.campus_name} onChange={e=>setMe({...me,campus_name:e.target.value})}/></label>
    <div className="two"><label>Время пути, мин.<input type="number" min="0" max="300" value={me.travel_minutes} onChange={e=>setMe({...me,travel_minutes:+e.target.value})}/></label><label>Сборы, мин.<input type="number" min="0" max="180" value={me.prep_minutes} onChange={e=>setMe({...me,prep_minutes:+e.target.value})}/></label></div>
    <label>Запас времени, мин.<input type="number" min="0" max="120" value={me.buffer_minutes} onChange={e=>setMe({...me,buffer_minutes:+e.target.value})}/></label><button className="primary">Сохранить настройки</button></form>}
    <div className="hint">Погода загружается из Open-Meteo по городу, указанному на русском языке. Реальные пробки и транспорт пока не подключены.</div>
  </section>}
  <footer>StudyPilot · MVP курсового проекта</footer>
 </main>
}
createRoot(document.getElementById('root')).render(<App/>);
